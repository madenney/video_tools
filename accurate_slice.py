#!/usr/bin/env python3
import argparse
import os
import sys

from slice_tools.slice_ops import boundary_slice
from slice_tools.timecode import parse_timecode


def ensure_output_dir(path):
    output_dir = os.path.dirname(os.path.abspath(path))
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Slice videos with frame-accurate boundaries by transcoding "
            "to an intraframe intermediate."
        ),
        epilog="Time format: ss, mm:ss, or hh:mm:ss (fractions in seconds ok).",
    )
    parser.add_argument("input_path", help="Input video file path.")
    parser.add_argument("output_path", help="Output video file path.")
    parser.add_argument("start", help="Start time (ss, mm:ss, or hh:mm:ss).")
    parser.add_argument("stop", help="Stop time (ss, mm:ss, or hh:mm:ss).")
    args = parser.parse_args()

    if not os.path.isfile(args.input_path):
        print(f"Input file not found: {args.input_path}", file=sys.stderr)
        return 1

    try:
        start_seconds = parse_timecode(args.start)
        end_seconds = parse_timecode(args.stop)
    except ValueError as exc:
        print(f"Invalid timecode: {exc}", file=sys.stderr)
        return 1

    if end_seconds <= start_seconds:
        print("Stop time must be greater than start time.", file=sys.stderr)
        return 1

    ensure_output_dir(args.output_path)
    boundary_slice(args.input_path, args.output_path, start_seconds, end_seconds)

    return 0


if __name__ == "__main__":
    sys.exit(main())
