#!/usr/bin/env python3
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import uuid

from flask import Flask, jsonify, request, render_template, send_file, Response

from slice_tools.slice_ops import boundary_slice
from slice_tools.ffmpeg_utils import probe_video_info, probe_duration, has_audio
from slice_tools.timecode import parse_timecode

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
WORKING_DIR = os.path.join(SCRIPT_DIR, ".working_copies")

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mts",
}

# Codecs the browser <video> element can decode
BROWSER_CODECS = {"h264", "h265", "hevc", "vp8", "vp9", "av1"}

# Containers the browser can demux
BROWSER_CONTAINERS = {".mp4", ".m4v", ".webm", ".mov"}

app = Flask(__name__, template_folder=os.path.join(SCRIPT_DIR, "templates"))

# In-memory job store: job_id -> {status, message, output_path, error}
jobs = {}
jobs_lock = threading.Lock()

# Working copy cache: original_path -> working_copy_path
working_cache = {}
working_cache_lock = threading.Lock()


def sanitize_timecode_for_filename(tc):
    return tc.replace(":", "-").replace(".", "_")


def check_format_status(path, codec):
    """Return 'ready', 'remux', or 'transcode'.

    'ready'     — file is already browser-playable and sliceable as-is.
    'remux'     — codec is good, just needs repackaging into mp4/webm (fast, lossless).
    'transcode' — exotic codec, needs full conversion to h264 mp4.
    """
    ext = os.path.splitext(path)[1].lower()
    codec = (codec or "").lower()
    with working_cache_lock:
        cached = working_cache.get(path)
    if cached and os.path.isfile(cached):
        return "ready"
    if codec in BROWSER_CODECS and ext in BROWSER_CONTAINERS:
        return "ready"
    if codec in BROWSER_CODECS:
        return "remux"
    return "transcode"


def get_output_extension(codec):
    """Pick container based on source codec."""
    codec = (codec or "").lower()
    if codec in ("vp8", "vp9"):
        return ".webm"
    return ".mp4"


@app.route("/")
def index():
    return render_template("slice.html")


@app.route("/api/pick")
def pick_file():
    exts = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))
    if shutil.which("zenity"):
        try:
            result = subprocess.run(
                ["zenity", "--file-selection",
                 "--title=Select a video file",
                 f"--file-filter=Video files | {exts}",
                 "--file-filter=All files | *"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip()
                if os.path.isfile(path):
                    return jsonify({"path": path})
                return jsonify({"error": f"Not a file: {path}"}), 400
            return jsonify({"error": "cancelled"}), 400
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Dialog timed out"}), 408
    return jsonify({"error": "no_picker"}), 501


@app.route("/api/prepare", methods=["POST"])
def prepare_working_copy():
    data = request.get_json(force=True)
    path = data.get("path", "")

    if not path or not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404

    with working_cache_lock:
        cached = working_cache.get(path)
    if cached and os.path.isfile(cached):
        return jsonify({"status": "ready"})

    try:
        info = probe_video_info(path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    codec = (info.get("codec_name") or "").lower()
    status = check_format_status(path, codec)
    if status == "ready":
        return jsonify({"status": "ready"})

    os.makedirs(WORKING_DIR, exist_ok=True)
    path_hash = hashlib.md5(path.encode()).hexdigest()[:12]
    basename = os.path.splitext(os.path.basename(path))[0]
    working_path = os.path.join(WORKING_DIR, f"{basename}_{path_hash}.mp4")

    is_remux = status == "remux"
    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {
            "status": "running",
            "message": "Remuxing..." if is_remux else "Transcoding to H.264...",
            "output_path": working_path,
            "error": None,
        }

    def worker():
        try:
            if is_remux:
                cmd = [
                    "ffmpeg", "-y", "-i", path,
                    "-c", "copy", "-movflags", "+faststart",
                    working_path,
                ]
            else:
                cmd = [
                    "ffmpeg", "-y", "-i", path,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart",
                    working_path,
                ]
            subprocess.run(cmd, check=True, capture_output=True)
            with working_cache_lock:
                working_cache[path] = working_path
            with jobs_lock:
                jobs[job_id]["status"] = "complete"
                jobs[job_id]["message"] = "Ready"
        except Exception as exc:
            with jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = f"Conversion failed: {exc}"
                jobs[job_id]["error"] = str(exc)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return jsonify({"job_id": job_id, "status": "preparing"})


@app.route("/api/probe")
def probe():
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404

    try:
        info = probe_video_info(path)
        duration = probe_duration(path)
        audio = has_audio(path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    codec = (info.get("codec_name") or "").lower()
    format_status = check_format_status(path, codec)

    info["duration"] = duration
    info["has_audio"] = audio
    info["path"] = path
    info["filename"] = os.path.basename(path)
    info["playable"] = format_status == "ready"
    info["format_status"] = format_status
    return jsonify(info)


@app.route("/video")
def serve_video():
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return "Not found", 404
    # Serve working copy if one was prepared
    with working_cache_lock:
        working = working_cache.get(path)
    if working and os.path.isfile(working):
        return send_file(working, conditional=True)
    return send_file(path, conditional=True)


@app.route("/api/slice", methods=["POST"])
def start_slice():
    data = request.get_json(force=True)
    input_path = data.get("path", "")
    start_tc = data.get("start", "")
    stop_tc = data.get("stop", "")

    if not input_path or not os.path.isfile(input_path):
        return jsonify({"error": "Input file not found"}), 404

    # Use working copy if one was prepared (converted to sliceable format)
    with working_cache_lock:
        slice_input = working_cache.get(input_path)
    if not slice_input or not os.path.isfile(slice_input):
        slice_input = input_path

    try:
        start_seconds = parse_timecode(start_tc)
    except ValueError as exc:
        return jsonify({"error": f"Invalid start timecode: {exc}"}), 400

    try:
        end_seconds = parse_timecode(stop_tc)
    except ValueError as exc:
        return jsonify({"error": f"Invalid stop timecode: {exc}"}), 400

    if end_seconds <= start_seconds:
        return jsonify({"error": "Stop time must be greater than start time"}), 400

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # Name output after original file, always .mp4 since working copy is h264
    basename = os.path.splitext(os.path.basename(input_path))[0]
    start_safe = sanitize_timecode_for_filename(start_tc)
    stop_safe = sanitize_timecode_for_filename(stop_tc)
    try:
        info = probe_video_info(slice_input)
        ext = get_output_extension(info.get("codec_name"))
    except Exception:
        ext = ".mp4"
    output_path = os.path.join(OUTPUT_DIR, f"{basename}_sliced_{start_safe}_{stop_safe}{ext}")

    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {
            "status": "running",
            "message": "Starting slice...",
            "output_path": output_path,
            "error": None,
        }

    def worker():
        try:
            with jobs_lock:
                jobs[job_id]["message"] = "Slicing video..."
            boundary_slice(slice_input, output_path, start_seconds, end_seconds)
            with jobs_lock:
                jobs[job_id]["status"] = "complete"
                jobs[job_id]["message"] = "Complete"
        except Exception as exc:
            with jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = str(exc)
                jobs[job_id]["error"] = str(exc)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "message": job["message"],
        "error": job["error"],
    })


@app.route("/api/job/<job_id>/stream")
def job_stream(job_id):
    def generate():
        import time
        last_msg = None
        while True:
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                yield f"data: {__import__('json').dumps({'status': 'error', 'message': 'Job not found'})}\n\n"
                break
            msg = {"status": job["status"], "message": job["message"], "error": job["error"]}
            if msg != last_msg:
                yield f"data: {__import__('json').dumps(msg)}\n\n"
                last_msg = msg
            if job["status"] in ("complete", "error"):
                break
            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/job/<job_id>/download")
def job_download(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return "Job not found", 404
    if job["status"] != "complete":
        return "Job not complete", 400
    return send_file(job["output_path"], as_attachment=True)


def main():
    parser = argparse.ArgumentParser(
        description="Web UI for frame-accurate video slicing."
    )
    parser.add_argument("-p", "--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    print(f"Starting slice UI at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
