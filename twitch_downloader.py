import argparse
import os
import shutil
import subprocess
import sys

UPDATE_INSTRUCTIONS = """yt-dlp install/update:
  pipx install yt-dlp
  pipx upgrade yt-dlp
  yt-dlp -U
  sudo apt install yt-dlp
"""

DEFAULT_TEMPLATE = "twitch_%(id)s.%(ext)s"


def ensure_yt_dlp():
    yt_dlp_path = shutil.which("yt-dlp")
    if not yt_dlp_path:
        print("Error: yt-dlp not found in PATH.", file=sys.stderr)
        print(UPDATE_INSTRUCTIONS, file=sys.stderr)
        sys.exit(1)
    return yt_dlp_path


def resolve_output_template(output_path):
    if not output_path:
        return os.path.join(os.getcwd(), DEFAULT_TEMPLATE)

    expanded = os.path.expanduser(output_path)
    ends_with_sep = expanded.endswith(os.path.sep) or expanded.endswith("/")
    is_template = "%(" in expanded
    has_extension = os.path.splitext(expanded)[1] != ""

    if os.path.isdir(expanded) or ends_with_sep or (not is_template and not has_extension):
        os.makedirs(expanded, exist_ok=True)
        return os.path.join(expanded, DEFAULT_TEMPLATE)

    output_dir = os.path.dirname(expanded)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    return expanded


def download_vod(url, output_template, audio_only):
    yt_dlp_path = ensure_yt_dlp()
    cmd = [yt_dlp_path, "-o", output_template]

    if audio_only:
        cmd += ["-f", "ba/best"]
    else:
        cmd += ["-f", "bv*+ba/best"]

    cmd.append(url)

    try:
        print(f"Downloading: {url}")
        subprocess.run(cmd, check=True, text=True)
        print(f"Downloaded successfully to {output_template}")
    except subprocess.CalledProcessError as exc:
        print(f"Error: yt-dlp failed with error code {exc.returncode}.")
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Download Twitch VODs using yt-dlp.",
        epilog=UPDATE_INSTRUCTIONS
        + "\nNote: If you see 'nsig extraction failed', update yt-dlp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "twitch_url",
        help="Twitch VOD URL (e.g., https://www.twitch.tv/videos/123456789)",
    )
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
    output_template = resolve_output_template(args.output_path)
    download_vod(args.twitch_url, output_template, args.audio_only)


if __name__ == "__main__":
    main()
