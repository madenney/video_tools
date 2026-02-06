import json
import shlex
import subprocess


def run_cmd(cmd, check=True):
    print("Executing command:", " ".join(shlex.quote(arg) for arg in cmd))
    return subprocess.run(cmd, check=check)


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
