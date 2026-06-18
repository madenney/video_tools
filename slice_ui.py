#!/usr/bin/env python3
import argparse
import hashlib
import logging
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
UPLOAD_DIR = os.path.join(SCRIPT_DIR, ".uploads")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "slice_ui.log")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("slice_ui")


def _detect_nvenc():
    """True if ffmpeg has CUDA hwaccel + the h264_nvenc encoder available."""
    try:
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=10).stdout
        hw = subprocess.run(["ffmpeg", "-hide_banner", "-hwaccels"],
                            capture_output=True, text=True, timeout=10).stdout
        return "h264_nvenc" in enc and "cuda" in hw
    except Exception:
        return False


HAS_NVENC = _detect_nvenc()

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mts",
}

# Codecs a browser <video> element can reliably decode. NOTE: HEVC/H.265 is
# deliberately excluded — Chrome/Firefox can't decode it, so it needs a proxy.
BROWSER_CODECS = {"h264", "vp8", "vp9", "av1"}

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


def _parse_ffmpeg_time(value):
    """Parse an ffmpeg '-progress' out_time (HH:MM:SS.micro) to seconds."""
    try:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return None


def run_ffmpeg_with_progress(cmd, duration, progress_cb):
    """Run an ffmpeg command, reporting 0-100 progress via progress_cb(pct).

    cmd must already include '-progress pipe:1 -nostats'. ffmpeg's normal log
    is merged into the same pipe; we parse out_time lines for progress and keep
    a rolling tail so a non-zero exit can surface a useful error message.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    tail = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line:
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)
        if duration and line.startswith("out_time="):
            secs = _parse_ffmpeg_time(line.split("=", 1)[1])
            if secs is not None:
                progress_cb(max(0.0, min(100.0, secs / duration * 100)))
    proc.wait()
    if proc.returncode != 0:
        msg = next((l for l in reversed(tail) if "=" not in l and l.strip()),
                   "ffmpeg failed")
        raise RuntimeError(msg)


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


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Fallback for browser drag-drop: the browser can't expose a dropped
    file's real path, so it sends the file blob instead. Save it locally and
    return a path the rest of the path-based pipeline can use."""
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "No file in upload"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type: {ext or '(none)'}"}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # Prefix with a short uuid so re-dropping a same-named file doesn't collide.
    base = os.path.basename(f.filename)
    saved_path = os.path.join(UPLOAD_DIR, f"{str(uuid.uuid4())[:8]}_{base}")
    f.save(saved_path)
    size_mb = os.path.getsize(saved_path) / 1e6
    log.info("UPLOAD %s (%.1f MB) -> %s", base, size_mb, saved_path)
    return jsonify({"path": saved_path})


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
    log.info("PREPARE [%s] %s codec=%s -> %s", job_id,
             "remux" if is_remux else "transcode", codec, os.path.basename(path))
    duration = probe_duration(path)
    with jobs_lock:
        jobs[job_id] = {
            "status": "running",
            "message": "Remuxing..." if is_remux else "Building H.264 preview...",
            "output_path": working_path,
            "error": None,
            "progress": 0,
        }

    def on_progress(pct):
        with jobs_lock:
            jobs[job_id]["progress"] = round(pct)

    def worker():
        progress_args = ["-progress", "pipe:1", "-nostats"]
        # Preview proxy only — fast, scaled to <=1280 wide. The real slice runs on
        # the original file at full quality, so this only has to play in a browser.
        # GPU pipeline (NVENC) is ~15x faster on real HEVC; CPU is the fallback.
        # Only the first audio track, downmixed to stereo: BluRay rips carry
        # several multichannel tracks and re-encoding them all dominates the
        # runtime (≈3x slower) for a preview that needs just one stereo track.
        gpu_cmd = [
            "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
            "-i", path, "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale_cuda=w=1280:h=-2:format=yuv420p",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "28",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart",
        ] + progress_args + [working_path]
        cpu_cmd = [
            "ffmpeg", "-y", "-i", path, "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale='min(1280,iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart",
        ] + progress_args + [working_path]
        remux_cmd = [
            "ffmpeg", "-y", "-i", path,
            "-c", "copy", "-movflags", "+faststart",
        ] + progress_args + [working_path]

        if is_remux:
            attempts = [("remux", remux_cmd)]
        elif HAS_NVENC:
            attempts = [("gpu", gpu_cmd), ("cpu", cpu_cmd)]
        else:
            attempts = [("cpu", cpu_cmd)]

        try:
            last_err = None
            for i, (kind, cmd) in enumerate(attempts):
                try:
                    on_progress(0)
                    run_ffmpeg_with_progress(cmd, duration, on_progress)
                    last_err = None
                    if kind == "gpu":
                        log.info("PREPARE [%s] used GPU (NVENC)", job_id)
                    break
                except Exception as exc:
                    last_err = exc
                    if i + 1 < len(attempts):
                        log.warning("PREPARE [%s] %s path failed (%s) — falling back to %s",
                                    job_id, kind, exc, attempts[i + 1][0])
            if last_err is not None:
                raise last_err

            with working_cache_lock:
                working_cache[path] = working_path
            with jobs_lock:
                jobs[job_id]["status"] = "complete"
                jobs[job_id]["message"] = "Ready"
                jobs[job_id]["progress"] = 100
            log.info("PREPARE [%s] complete -> %s", job_id, os.path.basename(working_path))
        except Exception as exc:
            with jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = f"Conversion failed: {exc}"
                jobs[job_id]["error"] = str(exc)
            log.error("PREPARE [%s] FAILED: %s", job_id, exc)

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

    # Always slice the ORIGINAL file at full quality. boundary_slice handles any
    # codec (it stream-copies the bulk and re-encodes only the cut points with
    # the matching encoder). The working copy is a downscaled preview proxy and
    # must never be the slice source.
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
    # Name output after original file; container picked from the source codec.
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
    log.info("SLICE [%s] %s [%s -> %s] -> %s", job_id,
             os.path.basename(input_path), start_tc, stop_tc,
             os.path.basename(output_path))

    def worker():
        try:
            with jobs_lock:
                jobs[job_id]["message"] = "Slicing video..."
            boundary_slice(slice_input, output_path, start_seconds, end_seconds)
            with jobs_lock:
                jobs[job_id]["status"] = "complete"
                jobs[job_id]["message"] = "Complete"
            log.info("SLICE [%s] complete -> %s", job_id, os.path.basename(output_path))
        except Exception as exc:
            with jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = str(exc)
                jobs[job_id]["error"] = str(exc)
            log.error("SLICE [%s] FAILED: %s", job_id, exc)

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
        "progress": job.get("progress"),
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
            msg = {"status": job["status"], "message": job["message"],
                   "error": job["error"], "progress": job.get("progress")}
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

    log.info("Starting slice UI at http://%s:%s (logging to %s)",
             args.host, args.port, LOG_FILE)
    log.info("Preview proxy acceleration: %s", "GPU (NVENC)" if HAS_NVENC else "CPU (libx264)")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
