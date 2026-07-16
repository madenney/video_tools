#!/usr/bin/env python3
import argparse
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid

from flask import Flask, jsonify, request, render_template, send_file, Response

from slice_tools.slice_ops import accurate_cut, boundary_slice, make_gif
from slice_tools.ffmpeg_utils import probe_video_info, probe_duration, has_audio, probe_audio_codec
from slice_tools.timecode import parse_timecode

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
WORKING_DIR = os.path.join(SCRIPT_DIR, ".working_copies")
WAVE_DIR = os.path.join(WORKING_DIR, "waves")
WINDOW_DIR = os.path.join(WORKING_DIR, "windows")
UPLOAD_DIR = os.path.join(SCRIPT_DIR, ".uploads")

# Preview windows: rather than transcoding a whole 45-minute HEVC episode up
# front (~1 min on GPU) just to play one frame, transcode a short block around
# wherever the user actually is. Blocks are grid-aligned so they cache and can
# be prefetched. OVERLAP gives playback a couple of seconds of runway to cross
# into the next block without a visible gap.
WINDOW_SEC = 60
WINDOW_OVERLAP = 2
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

# Audio codecs a browser can decode. AC-3/E-AC-3 (DD/DDP), DTS, TrueHD are NOT
# here — a WEB-DL with H.264 video plays picture but silence unless the audio is
# re-encoded, which is exactly what the windowed preview does.
BROWSER_AUDIO = {"aac", "mp3", "opus", "vorbis", "flac"}

# Containers the browser can demux
BROWSER_CONTAINERS = {".mp4", ".m4v", ".webm", ".mov"}

app = Flask(__name__, template_folder=os.path.join(SCRIPT_DIR, "templates"))

# In-memory job store: job_id -> {status, message, output_path, error, progress}
jobs = {}
jobs_lock = threading.Lock()


def sanitize_timecode_for_filename(tc):
    return tc.replace(":", "-").replace(".", "_")


def resolve_output_dir(input_path):
    """Where a cut of `input_path` should land: next to the source by default.

    Falls back to OUTPUT_DIR when the source sits somewhere a cut has no business
    going — our own internal caches (a dropped-file copy in .uploads/ isn't where
    the user thinks their video lives) — or when the directory isn't writable,
    e.g. a read-only mount or an SD card pulled mid-session.
    """
    src_dir = os.path.dirname(os.path.abspath(input_path))
    internal = (os.path.abspath(UPLOAD_DIR), os.path.abspath(WORKING_DIR))
    if any(src_dir == d or src_dir.startswith(d + os.sep) for d in internal):
        return OUTPUT_DIR
    if not os.access(src_dir, os.W_OK):
        log.info("OUTPUT %s not writable — falling back to output/", src_dir)
        return OUTPUT_DIR
    return src_dir


def check_format_status(path, codec, audio_codec=None):
    """Return 'ready' if the browser can play the file as-is, else 'windowed'.

    'ready'    — stream the original straight to the player.
    'windowed' — the browser can't decode the video OR the audio (or can't demux
                 the container), so preview it through on-demand blocks
                 (see /media/window), which re-encode both to browser codecs.
    """
    ext = os.path.splitext(path)[1].lower()
    codec = (codec or "").lower()
    audio_codec = (audio_codec or "").lower()
    video_ok = codec in BROWSER_CODECS and ext in BROWSER_CONTAINERS
    audio_ok = not audio_codec or audio_codec in BROWSER_AUDIO
    return "ready" if (video_ok and audio_ok) else "windowed"


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


def _locate_roots():
    """Directories worth searching for a dropped file, cheapest first."""
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, d)
        for d in ("Videos", "Downloads", "Desktop", "Movies", "Pictures", "Projects")
    ]
    # Removable media / mounts — where camera cards and external drives land.
    for base in ("/media", "/mnt", "/run/media"):
        if os.path.isdir(base):
            for entry in os.listdir(base):
                roots.append(os.path.join(base, entry))
    return [r for r in roots if os.path.isdir(r)]


@app.route("/api/locate", methods=["POST"])
def locate_file():
    """Find a dropped file on disk by name (+ size) so we can load it in place.

    A browser drop exposes only a blob, never a path — but it does give us the
    filename and byte size. Searching for that beats copying gigabytes through
    an upload just to learn where the file already lives.
    """
    data = request.get_json(force=True)
    name = os.path.basename(data.get("name", "") or "")
    size = data.get("size")

    if not name:
        return jsonify({"error": "No filename"}), 400

    # Roots are ordered cheapest/likeliest first and we return on the first
    # size-verified hit — walking every mounted drive to completion takes ~8s,
    # and a name+size match is already the file.
    # A hit returns in milliseconds; only a genuine miss walks to the deadline,
    # so keep that short — the user is watching a spinner for it.
    deadline = time.monotonic() + 6.0
    for root in _locate_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            if time.monotonic() > deadline:
                log.info("LOCATE timed out: %s", name)
                return jsonify({"found": False})
            # Skip hidden trees (.git, .cache, our own .working_copies, ...)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if name not in filenames:
                continue
            candidate = os.path.join(dirpath, name)
            try:
                if size is None or os.path.getsize(candidate) == int(size):
                    log.info("LOCATE hit: %s -> %s", name, candidate)
                    return jsonify({"found": True, "path": candidate})
            except OSError:
                pass

    log.info("LOCATE miss: %s", name)
    return jsonify({"found": False})


@app.route("/api/probe")
def probe():
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404

    try:
        info = probe_video_info(path)
        duration = probe_duration(path)
        audio_codec = probe_audio_codec(path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    codec = (info.get("codec_name") or "").lower()
    format_status = check_format_status(path, codec, audio_codec)

    info["duration"] = duration
    info["has_audio"] = audio_codec is not None
    info["audio_codec"] = audio_codec
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
    # Only browser-playable files reach here; anything else is previewed through
    # /media/window instead.
    return send_file(path, conditional=True)


def _window_bounds(idx):
    """Absolute (start, length) seconds for grid block `idx`."""
    return idx * WINDOW_SEC, WINDOW_SEC + WINDOW_OVERLAP


# One lock per (path, idx) so two players racing for the same block build it once.
window_locks = {}
window_locks_guard = threading.Lock()


def _window_lock(key):
    with window_locks_guard:
        lock = window_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            window_locks[key] = lock
        return lock


def build_window(path, idx):
    """Transcode one preview block, cached on disk. Returns its path."""
    os.makedirs(WINDOW_DIR, exist_ok=True)
    path_hash = hashlib.md5(path.encode()).hexdigest()[:12]
    out_path = os.path.join(WINDOW_DIR, f"{path_hash}_{idx:05d}.mp4")

    with _window_lock((path, idx)):
        if os.path.isfile(out_path):
            return out_path

        start, length = _window_bounds(idx)
        # -ss BEFORE -i: seek to the preceding keyframe, then decode and discard
        # up to the exact start. With a re-encode the block begins precisely at
        # `start`, so proxy time 0 == start and the offset math stays honest.
        gpu_cmd = [
            "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
            "-ss", f"{start:.3f}", "-i", path, "-t", f"{length:.3f}",
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale_cuda=w=1280:h=-2:format=yuv420p",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "28",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            "-movflags", "+faststart", out_path,
        ]
        cpu_cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}", "-i", path, "-t", f"{length:.3f}",
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "scale='min(1280,iw)':-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            "-movflags", "+faststart", out_path,
        ]
        attempts = [gpu_cmd, cpu_cmd] if HAS_NVENC else [cpu_cmd]

        last_err = None
        for cmd in attempts:
            t0 = time.monotonic()
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=180)
                log.info("WINDOW [%s idx=%d] built in %.1fs", os.path.basename(path),
                         idx, time.monotonic() - t0)
                return out_path
            except Exception as exc:
                last_err = exc
                if os.path.isfile(out_path):
                    os.remove(out_path)  # don't cache a half-written block
        raise RuntimeError(f"window build failed: {last_err}")


@app.route("/media/window")
def serve_window():
    """Serve one preview block. Built on demand, then cached."""
    path = request.args.get("path", "")
    try:
        idx = int(request.args.get("idx", "0"))
    except ValueError:
        return "Bad idx", 400
    if not path or not os.path.isfile(path) or idx < 0:
        return "Not found", 404

    try:
        out_path = build_window(path, idx)
    except Exception as exc:
        log.error("WINDOW [%s idx=%d] FAILED: %s", os.path.basename(path), idx, exc)
        return "Window build failed", 500
    return send_file(out_path, conditional=True)


@app.route("/media/wave")
def serve_wave():
    """A waveform PNG for the whole file, drawn behind the timeline.

    Decodes the source's audio once and caches the result on disk, keyed by path.
    Loaded async by the <img>, so a slow build never holds up playback.
    """
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        return "Not found", 404

    os.makedirs(WAVE_DIR, exist_ok=True)
    path_hash = hashlib.md5(path.encode()).hexdigest()[:12]
    wave_path = os.path.join(WAVE_DIR, f"{path_hash}.png")
    if os.path.isfile(wave_path):
        return send_file(wave_path, mimetype="image/png")

    if not has_audio(path):
        return "No audio", 404

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", path,
        "-filter_complex", "showwavespic=s=2000x120:colors=#7aa2f7",
        "-frames:v", "1", wave_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except Exception as exc:
        log.warning("WAVE failed for %s: %s", os.path.basename(path), exc)
        return "Waveform failed", 500

    log.info("WAVE built -> %s", os.path.basename(wave_path))
    return send_file(wave_path, mimetype="image/png")


def _scene_cuts(source, start_s, dur_s, thresh=0.3):
    """Seconds (absolute) of scene changes inside a window of the source."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_s:.3f}", "-i", source, "-t", f"{dur_s:.3f}",
        "-vf", f"select='gt(scene,{thresh})',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except Exception as exc:
        log.warning("SNAP scene detect failed: %s", exc)
        return []
    cuts = []
    for line in out.splitlines():
        if "pts_time:" in line:
            try:
                cuts.append(start_s + float(line.split("pts_time:")[1].split()[0]))
            except (ValueError, IndexError):
                pass
    return cuts


@app.route("/api/snapcuts", methods=["POST"])
def snap_cuts():
    """Snap a trim edge to the nearest hard scene cut within +/- WINDOW.

    Start lands one frame *after* the cut and end one frame *before* it, so the
    slice never includes a frame from the neighbouring shot (the "double-cut
    flash").
    """
    data = request.get_json(force=True)
    path = data.get("path", "")
    edge = data.get("edge", "start")
    try:
        edge_s = float(data.get("edge_seconds"))
    except (TypeError, ValueError):
        return jsonify({"error": "edge_seconds required"}), 400

    if not path or not os.path.isfile(path):
        return jsonify({"error": "File not found"}), 404

    WINDOW = 0.3  # seconds either side
    try:
        info = probe_video_info(path)
        fps = 30.0
        rate = info.get("r_frame_rate") or ""
        if "/" in rate:
            num, den = rate.split("/")
            if float(den):
                fps = float(num) / float(den)
    except Exception:
        fps = 30.0
    frame = 1.0 / fps

    start_s = max(0.0, edge_s - WINDOW)
    # 0.3 is a hard cut. Softer material (screen caps, dim scenes) never trips it,
    # so fall back to a looser threshold rather than reporting "no cut" on a cut.
    cuts = _scene_cuts(path, start_s, WINDOW * 2, thresh=0.3)
    if not cuts:
        cuts = _scene_cuts(path, start_s, WINDOW * 2, thresh=0.15)
    if not cuts:
        return jsonify({"ok": True, "cut": None})

    nearest = min(cuts, key=lambda c: abs(c - edge_s))
    snapped = nearest + frame if edge == "start" else max(0.0, nearest - frame)
    log.info("SNAP [%s] %.3f -> %.3f", edge, edge_s, snapped)
    return jsonify({"ok": True, "cut": nearest, "seconds": snapped})


@app.route("/api/slice", methods=["POST"])
def start_slice():
    data = request.get_json(force=True)
    input_path = data.get("path", "")
    start_tc = data.get("start", "")
    stop_tc = data.get("stop", "")
    # "accurate" re-encodes the whole span: exact frame count, slower.
    # "fast" stream-copies the bulk: quicker, but the cut snaps to keyframes and
    # can run a couple of frames long.
    mode = data.get("mode", "accurate")

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

    # Name output after original file; container picked from the source codec.
    basename = os.path.splitext(os.path.basename(input_path))[0]
    start_safe = sanitize_timecode_for_filename(start_tc)
    stop_safe = sanitize_timecode_for_filename(stop_tc)
    if mode == "gif":
        ext = ".gif"
    else:
        try:
            info = probe_video_info(slice_input)
            ext = get_output_extension(info.get("codec_name"))
        except Exception:
            ext = ".mp4"

    out_dir = resolve_output_dir(input_path)
    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, f"{basename}_sliced_{start_safe}_{stop_safe}{ext}")

    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {
            "status": "running",
            "message": "Starting slice...",
            "output_path": output_path,
            "error": None,
            "progress": 0,
        }
    log.info("SLICE [%s] %s mode=%s [%s -> %s] -> %s", job_id,
             os.path.basename(input_path), mode, start_tc, stop_tc,
             os.path.basename(output_path))

    def on_progress(pct):
        with jobs_lock:
            jobs[job_id]["progress"] = round(pct)

    msg_for_mode = {
        "gif": "Making GIF...",
        "fast": "Cutting (fast)...",
        "accurate": "Cutting (frame-accurate)...",
    }

    def worker():
        try:
            with jobs_lock:
                jobs[job_id]["message"] = msg_for_mode.get(mode, "Cutting...")
            if mode == "gif":
                make_gif(slice_input, output_path, start_seconds, end_seconds,
                         progress_cb=on_progress)
            elif mode == "fast":
                boundary_slice(slice_input, output_path, start_seconds, end_seconds)
            else:
                used = accurate_cut(slice_input, output_path, start_seconds,
                                    end_seconds, progress_cb=on_progress)
                log.info("SLICE [%s] encoded on %s", job_id, used.upper())
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
        "output_path": job.get("output_path"),
    })


@app.route("/api/job/<job_id>/stream")
def job_stream(job_id):
    def generate():
        last_msg = None
        while True:
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                yield f"data: {__import__('json').dumps({'status': 'error', 'message': 'Job not found'})}\n\n"
                break
            msg = {"status": job["status"], "message": job["message"],
                   "error": job["error"], "progress": job.get("progress"),
                   "output_path": job.get("output_path")}
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
