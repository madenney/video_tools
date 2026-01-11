# Written almost entirely by ChatGPT4

import shlex
import subprocess


def apply_overlay(video_path, overlay_image_path, output_video_path):
    cmd = [
        "ffmpeg",
        "-i",
        video_path,
        "-i",
        overlay_image_path,
        "-filter_complex",
        "[0:v][1:v]scale2ref[vid][ovr];[vid][ovr]overlay=format=auto:0:0",
        "-codec:a",
        "copy",
        output_video_path,
    ]

    print("Executing command:", " ".join(shlex.quote(arg) for arg in cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Apply a PNG overlay to a video using ffmpeg.")
    parser.add_argument("video_path", help="Input video path")
    parser.add_argument("overlay_image_path", help="Overlay PNG path")
    parser.add_argument("output_video_path", help="Output video path")

    args = parser.parse_args()
    apply_overlay(args.video_path, args.overlay_image_path, args.output_video_path)
