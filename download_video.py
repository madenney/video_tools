#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(__file__)

SOURCE_PATTERNS = {
    "youtube": re.compile(
        r"(https?://)?(www\.)?(m\.)?(youtube\.com/watch\?v=|youtube\.com/shorts/|youtube\.com/live/|youtu\.be/)",
        re.IGNORECASE,
    ),
    "twitter": re.compile(
        r"(https?://)?(www\.)?(twitter\.com|x\.com)/.+/status/\d+",
        re.IGNORECASE,
    ),
    "twitch": re.compile(
        r"(https?://)?(www\.)?twitch\.tv/(videos/\d+|[^/]+/video/\d+)",
        re.IGNORECASE,
    ),
}

SCRIPT_MAP = {
    "youtube": "yt_downloader.py",
    "twitter": "twitter_downloader.py",
    "twitch": "twitch_downloader.py",
}


def detect_source(url):
    for source, pattern in SOURCE_PATTERNS.items():
        if pattern.search(url):
            return source
    return None


def dispatch(source, url, output_path, audio_only):
    script_name = SCRIPT_MAP[source]
    script_path = os.path.join(SCRIPT_DIR, script_name)
    cmd = [sys.executable, script_path, url]
    if output_path:
        cmd.append(output_path)
    if audio_only:
        cmd.append("--audio-only")

    result = subprocess.run(cmd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Download videos from YouTube, Twitch, or Twitter/X.",
    )
    parser.add_argument("url", help="YouTube/Twitch/Twitter/X URL")
    parser.add_argument(
        "output_path",
        nargs="?",
        help="Output directory or file/template (default: current directory).",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download audio only (best available audio).",
    )
    args = parser.parse_args()

    source = detect_source(args.url)
    if not source:
        print("Unrecognized URL. Expected YouTube, Twitch, or Twitter/X.", file=sys.stderr)
        sys.exit(1)

    sys.exit(dispatch(source, args.url, args.output_path, args.audio_only))


if __name__ == "__main__":
    main()
