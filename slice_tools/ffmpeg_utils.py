import json
import shlex
import subprocess


def run_cmd(cmd, check=True):
    print("Executing command:", " ".join(shlex.quote(arg) for arg in cmd))
    return subprocess.run(cmd, check=check)


def _parse_ffmpeg_time(value):
    """Parse an ffmpeg '-progress' out_time (HH:MM:SS.micro) into seconds."""
    try:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return None


def run_cmd_with_progress(cmd, duration, progress_cb):
    """Run ffmpeg, reporting 0-100 progress via progress_cb(pct).

    '-progress pipe:1 -nostats' is appended here, so callers pass a plain command.
    A rolling tail of the log is kept so a non-zero exit can raise something more
    useful than "ffmpeg failed".
    """
    cmd = list(cmd)
    # -progress must come before the output path, which is always last.
    cmd[-1:-1] = ["-progress", "pipe:1", "-nostats"]
    print("Executing command:", " ".join(shlex.quote(arg) for arg in cmd))

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    tail = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line:
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)
        if duration and progress_cb and line.startswith("out_time="):
            secs = _parse_ffmpeg_time(line.split("=", 1)[1])
            if secs is not None:
                progress_cb(max(0.0, min(100.0, secs / duration * 100)))
    proc.wait()
    if proc.returncode != 0:
        msg = next((l for l in reversed(tail) if "=" not in l and l.strip()),
                   "ffmpeg failed")
        raise RuntimeError(msg)


_nvenc_cache = None


def has_nvenc():
    """True if ffmpeg exposes the NVENC encoders (cached after the first call)."""
    global _nvenc_cache
    if _nvenc_cache is None:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                 capture_output=True, text=True, timeout=10).stdout
            _nvenc_cache = "h264_nvenc" in out
        except Exception:
            _nvenc_cache = False
    return _nvenc_cache


def probe_stream_types(path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
    data = json.loads(result.stdout) if result.stdout else {}
    streams = data.get("streams", [])
    return [
        stream.get("codec_type")
        for stream in streams
        if stream.get("codec_type")
    ]


def has_audio(path):
    return "audio" in probe_stream_types(path)


def probe_video_info(path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,bit_rate,r_frame_rate,pix_fmt",
        "-show_entries",
        "format=bit_rate",
        "-of",
        "json",
        path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
    data = json.loads(result.stdout) if result.stdout else {}
    stream = data.get("streams", [{}])[0]
    fmt = data.get("format", {})
    bitrate = stream.get("bit_rate") or fmt.get("bit_rate")
    return {
        "codec_name": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "bit_rate": int(bitrate) if bitrate else None,
        "r_frame_rate": stream.get("r_frame_rate"),
        "pix_fmt": stream.get("pix_fmt"),
    }


def probe_duration(path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
    data = json.loads(result.stdout) if result.stdout else {}
    duration = data.get("format", {}).get("duration")
    return float(duration) if duration else None
