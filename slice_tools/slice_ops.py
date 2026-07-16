import os
import tempfile

from slice_tools.ffmpeg_utils import (
    has_audio,
    has_nvenc,
    probe_duration,
    probe_video_info,
    run_cmd,
    run_cmd_with_progress,
)
from slice_tools.timecode import format_seconds


def convert_to_intraframe(input_path, output_path):
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "ffv1",
        "-level",
        "3",
        "-c:a",
        "flac",
        "-sn",
        "-dn",
        output_path,
    ]
    run_cmd(cmd)


def slice_precise(input_path, output_path, start_seconds, end_seconds):
    start_ts = format_seconds(start_seconds)
    end_ts = format_seconds(end_seconds)
    audio = has_audio(input_path)

    if audio:
        filter_complex = (
            f"[0:v]trim=start={start_ts}:end={end_ts},setpts=PTS-STARTPTS[v];"
            f"[0:a]atrim=start={start_ts}:end={end_ts},asetpts=PTS-STARTPTS[a]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ]
    else:
        filter_complex = (
            f"[0:v]trim=start={start_ts}:end={end_ts},setpts=PTS-STARTPTS[v]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            output_path,
        ]

    run_cmd(cmd)


CODEC_MAP = {
    "h264": "libx264",
    "hevc": "libx265",
    "h265": "libx265",
    "vp9": "libvpx-vp9",
    "av1": "libsvtav1",
}


def build_encoder_args(video_info):
    codec = video_info.get("codec_name") or ""
    encoder = CODEC_MAP.get(codec, "libx264")
    args = ["-c:v", encoder]
    bitrate = video_info.get("bit_rate")
    if bitrate:
        args += ["-b:v", str(bitrate)]
    else:
        args += ["-crf", "18"]
    if encoder in ("libx264", "libx265"):
        args += ["-preset", "medium"]
    pix_fmt = video_info.get("pix_fmt")
    if pix_fmt:
        args += ["-pix_fmt", pix_fmt]
    return args


NVENC_MAP = {"libx264": "h264_nvenc", "libx265": "hevc_nvenc"}

# NVENC rejects some of the pixel formats the CPU encoders accept: it wants the
# semi-planar form of 10-bit, and it has no notion of the full-range JPEG
# variants that camera H.264 uses.
NVENC_PIX_FMT = {
    "yuv420p10le": "p010le",
    "yuv444p10le": "p010le",
    "yuvj420p": "yuv420p",
    "yuvj422p": "yuv420p",
    "yuvj444p": "yuv444p",
}


def build_gpu_encoder_args(video_info):
    """NVENC equivalent of build_encoder_args, or None if the codec has no NVENC
    encoder (in which case the caller should stay on the CPU)."""
    codec = video_info.get("codec_name") or ""
    cpu_encoder = CODEC_MAP.get(codec, "libx264")
    encoder = NVENC_MAP.get(cpu_encoder)
    if encoder is None:
        return None

    args = ["-c:v", encoder, "-preset", "p5"]
    bitrate = video_info.get("bit_rate")
    if bitrate:
        args += ["-b:v", str(bitrate), "-maxrate", str(int(bitrate * 1.5)),
                 "-bufsize", str(int(bitrate * 2))]
    else:
        args += ["-cq", "19"]

    pix_fmt = video_info.get("pix_fmt")
    if pix_fmt:
        args += ["-pix_fmt", NVENC_PIX_FMT.get(pix_fmt, pix_fmt)]
    return args


def accurate_cut(input_path, output_path, start_seconds, end_seconds,
                 video_info=None, prefer_gpu=True, progress_cb=None):
    """Frame-accurate cut by re-encoding the selected span with an accurate seek.

    ``-ss`` before ``-i`` seeks to the preceding keyframe, then decodes and
    discards up to the exact start, so the output begins precisely at
    ``start_seconds`` no matter how sparse the keyframes are. The whole span is
    re-encoded, which is exact — unlike boundary_slice, whose stream-copied
    middle snaps to keyframe boundaries and can run a couple of frames long.

    Re-encoding every frame is the expensive part, so try NVENC first and fall
    back to the CPU encoder if the GPU path fails for any reason (no NVENC, an
    unsupported pixel format, a busy card).
    """
    if video_info is None:
        video_info = probe_video_info(input_path)
    duration = max(0.0, end_seconds - start_seconds)
    audio = has_audio(input_path)

    def build(encoder_args):
        cmd = [
            "ffmpeg", "-y",
            "-ss", format_seconds(start_seconds),
            "-i", input_path,
            "-t", format_seconds(duration),
            "-map", "0:v:0",
        ]
        if audio:
            cmd += ["-map", "0:a?"]
        cmd += encoder_args
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-map_chapters", "-1", "-avoid_negative_ts", "make_zero", output_path]
        return cmd

    attempts = []
    if prefer_gpu and has_nvenc():
        gpu_args = build_gpu_encoder_args(video_info)
        if gpu_args:
            attempts.append(("gpu", build(gpu_args)))
    attempts.append(("cpu", build(build_encoder_args(video_info))))

    last_err = None
    for i, (kind, cmd) in enumerate(attempts):
        try:
            if progress_cb:
                run_cmd_with_progress(cmd, duration, progress_cb)
            else:
                run_cmd(cmd)
            return kind
        except Exception as exc:
            last_err = exc
            if i + 1 < len(attempts):
                print(f"accurate_cut: {kind} path failed ({exc}) — falling back to "
                      f"{attempts[i + 1][0]}")
    raise RuntimeError(f"accurate_cut failed: {last_err}")


def make_gif(input_path, output_path, start_seconds, end_seconds,
             fps=15, width=640, progress_cb=None):
    """Cut a range to an animated GIF via a two-pass palette for decent color.

    A single-pass GIF quantizes to a generic 256-colour table and bands badly.
    palettegen builds a palette from this exact clip; paletteuse then dithers
    against it. Scaled down and frame-rate reduced because GIF is huge otherwise.
    """
    duration = max(0.0, end_seconds - start_seconds)
    filters = f"fps={fps},scale={width}:-1:flags=lanczos"

    with tempfile.TemporaryDirectory(prefix="gif_") as tmpdir:
        palette = os.path.join(tmpdir, "palette.png")
        run_cmd([
            "ffmpeg", "-y",
            "-ss", format_seconds(start_seconds), "-t", format_seconds(duration),
            "-i", input_path,
            "-vf", f"{filters},palettegen=stats_mode=diff",
            palette,
        ])
        gen = [
            "ffmpeg", "-y",
            "-ss", format_seconds(start_seconds), "-t", format_seconds(duration),
            "-i", input_path, "-i", palette,
            "-lavfi", f"{filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
            "-loop", "0", output_path,
        ]
        if progress_cb:
            run_cmd_with_progress(gen, duration, progress_cb)
        else:
            run_cmd(gen)


def stream_copy_segment(input_path, output_path, start, end):
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        format_seconds(start),
        "-to",
        format_seconds(end),
        "-i",
        input_path,
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        output_path,
    ]
    run_cmd(cmd)


def cut_and_encode_segment(input_path, output_path, start, end, video_info):
    start_ts = format_seconds(start)
    end_ts = format_seconds(end)
    audio = has_audio(input_path)

    encoder_args = build_encoder_args(video_info)

    if audio:
        filter_complex = (
            f"[0:v]trim=start={start_ts}:end={end_ts},setpts=PTS-STARTPTS[v];"
            f"[0:a]atrim=start={start_ts}:end={end_ts},asetpts=PTS-STARTPTS[a]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
        ] + encoder_args + [
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ]
    else:
        filter_complex = (
            f"[0:v]trim=start={start_ts}:end={end_ts},setpts=PTS-STARTPTS[v]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
        ] + encoder_args + [
            output_path,
        ]

    run_cmd(cmd)


def concat_segments(segment_paths, output_path, tmpdir):
    list_file = os.path.join(tmpdir, "concat_list.txt")
    with open(list_file, "w") as f:
        for seg in segment_paths:
            f.write(f"file {seg!r}\n")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_file,
        "-c",
        "copy",
        output_path,
    ]
    run_cmd(cmd)


def boundary_slice(input_path, output_path, start_seconds, end_seconds):
    video_info = probe_video_info(input_path)
    duration = probe_duration(input_path)

    margin = 2.0
    chunk_a_start = max(0, start_seconds - margin)
    chunk_a_end = min(start_seconds + margin, end_seconds)
    chunk_b_start = max(end_seconds - margin, start_seconds)
    chunk_b_end = min(end_seconds + margin, duration) if duration else end_seconds + margin

    boundaries_overlap = chunk_a_end >= chunk_b_start

    with tempfile.TemporaryDirectory(prefix="accurate_slice_") as tmpdir:
        if boundaries_overlap:
            # Short clip — single region re-encode
            region_start = chunk_a_start
            region_end = chunk_b_end
            chunk_raw = os.path.join(tmpdir, "chunk_raw.mkv")
            chunk_intra = os.path.join(tmpdir, "chunk_intra.mkv")

            stream_copy_segment(input_path, chunk_raw, region_start, region_end)
            convert_to_intraframe(chunk_raw, chunk_intra)

            # Cut positions relative to the extracted chunk
            rel_start = start_seconds - region_start
            rel_end = end_seconds - region_start
            cut_and_encode_segment(chunk_intra, output_path, rel_start, rel_end, video_info)
        else:
            segments = []

            # Chunk A: boundary around start point
            chunk_a_raw = os.path.join(tmpdir, "chunk_a_raw.mkv")
            chunk_a_intra = os.path.join(tmpdir, "chunk_a_intra.mkv")
            chunk_a_cut = os.path.join(tmpdir, "chunk_a_cut.mkv")

            stream_copy_segment(input_path, chunk_a_raw, chunk_a_start, chunk_a_end)
            convert_to_intraframe(chunk_a_raw, chunk_a_intra)

            rel_start_a = start_seconds - chunk_a_start
            rel_end_a = chunk_a_end - chunk_a_start
            cut_and_encode_segment(chunk_a_intra, chunk_a_cut, rel_start_a, rel_end_a, video_info)
            segments.append(chunk_a_cut)

            # Middle: stream-copy the bulk
            middle_start = start_seconds + margin
            middle_end = end_seconds - margin
            if middle_end > middle_start:
                middle_seg = os.path.join(tmpdir, "middle.mkv")
                stream_copy_segment(input_path, middle_seg, middle_start, middle_end)
                segments.append(middle_seg)

            # Chunk B: boundary around stop point
            chunk_b_raw = os.path.join(tmpdir, "chunk_b_raw.mkv")
            chunk_b_intra = os.path.join(tmpdir, "chunk_b_intra.mkv")
            chunk_b_cut = os.path.join(tmpdir, "chunk_b_cut.mkv")

            stream_copy_segment(input_path, chunk_b_raw, chunk_b_start, chunk_b_end)
            convert_to_intraframe(chunk_b_raw, chunk_b_intra)

            rel_start_b = 0
            rel_end_b = end_seconds - chunk_b_start
            cut_and_encode_segment(chunk_b_intra, chunk_b_cut, rel_start_b, rel_end_b, video_info)
            segments.append(chunk_b_cut)

            if len(segments) == 1:
                os.replace(segments[0], output_path)
            else:
                concat_segments(segments, output_path, tmpdir)
