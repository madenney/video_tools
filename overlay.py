# Written almost entirely by ChatGPT4

import json
import os
import subprocess
import sys
import tempfile

from apply_overlay import apply_overlay
from generate_overlay import create_text_overlay

USAGE = """Usage:
  python overlay.py <video_file_path> <video_output_path> <overlay_text> [overlay_text_bottom_right]
  python overlay.py -t <width> <height> <overlay_text> <overlay_output_path> [overlay_text_bottom_right]

Options:
  -h, --help   Show this help message and exit.
  -t, --test   Generate overlay image only (no video required).
"""


def get_video_dimensions(video_path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        video_path,
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    video_info = json.loads(result.stdout)
    width = video_info["streams"][0]["width"]
    height = video_info["streams"][0]["height"]
    return width, height


def print_usage(exit_code):
    print(USAGE)
    sys.exit(exit_code)


def main():
    args = sys.argv[1:]

    if not args:
        print_usage(1)

    if "-h" in args or "--help" in args:
        print_usage(0)

    if "-t" in args or "--test" in args:
        args = [arg for arg in args if arg not in ("-t", "--test")]
        if len(args) not in (4, 5):
            print_usage(1)

        width = int(args[0])
        height = int(args[1])
        overlay_text = args[2]
        overlay_output_path = args[3]
        overlay_text_2 = args[4] if len(args) == 5 else None

        create_text_overlay(
            width,
            height,
            overlay_text,
            overlay_text_2,
            overlay_output_path,
        )
        return

    if len(args) not in (3, 4):
        print_usage(1)

    video_file_path = args[0]
    video_output_path = args[1]
    overlay_text = args[2]
    overlay_text_2 = args[3] if len(args) == 4 else None

    width, height = get_video_dimensions(video_file_path)

    with tempfile.TemporaryDirectory(prefix="overlay_") as tmpdir:
        overlay_image_path = os.path.join(tmpdir, "overlay.png")
        create_text_overlay(
            width,
            height,
            overlay_text,
            overlay_text_2,
            overlay_image_path,
        )
        apply_overlay(video_file_path, overlay_image_path, video_output_path)


if __name__ == "__main__":
    main()
