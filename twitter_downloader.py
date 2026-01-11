import argparse
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(__file__)
DEFAULT_TEMPLATE = "tweet_%(id)s.%(ext)s"
ENV_INSTRUCTIONS = """Optional .env:
  YT_DLP_PATH=/path/to/yt-dlp
"""
UPDATE_INSTRUCTIONS = """yt-dlp install/update:
  pipx install yt-dlp
  pipx upgrade yt-dlp
  yt-dlp -U
  sudo apt install yt-dlp
"""


def load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def load_environment():
    load_dotenv(os.path.join(os.getcwd(), ".env"))
    load_dotenv(os.path.join(SCRIPT_DIR, ".env"))


def resolve_yt_dlp_path():
    env_path = os.getenv("YT_DLP_PATH")
    if env_path:
        expanded = os.path.expanduser(env_path)
        if not os.path.isfile(expanded):
            print(f"Error: YT_DLP_PATH does not exist: {expanded}", file=sys.stderr)
            sys.exit(1)
        return expanded

    yt_dlp_path = shutil.which("yt-dlp")
    if not yt_dlp_path:
        print("Error: yt-dlp not found in PATH.", file=sys.stderr)
        print(UPDATE_INSTRUCTIONS, file=sys.stderr)
        sys.exit(1)
    return yt_dlp_path


def ensure_ffmpeg():
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg is required for --audio-only.", file=sys.stderr)
        sys.exit(1)


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


def download_tweet(tweet_url, output_template, audio_only):
    yt_dlp_path = resolve_yt_dlp_path()
    cmd = [yt_dlp_path, "-o", output_template]

    if audio_only:
        ensure_ffmpeg()
        cmd += ["-f", "ba/best", "-x", "--audio-format", "m4a", "--audio-quality", "0"]
    else:
        cmd += ["-f", "bv*+ba/best"]

    cmd.append(tweet_url)

    try:
        print(f"Downloading: {tweet_url}")
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
        description="Download Twitter/X video or GIF media using yt-dlp.",
        epilog=ENV_INSTRUCTIONS
        + "\n"
        + UPDATE_INSTRUCTIONS
        + "\nNote: If you see 'nsig extraction failed', update yt-dlp.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("tweet_url", help="Tweet URL (twitter.com or x.com)")
    parser.add_argument(
        "output_path",
        nargs="?",
        help="Output directory or file/template (default: current directory).",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Extract audio to .m4a (requires ffmpeg).",
    )

    args = parser.parse_args()

    load_environment()
    output_template = resolve_output_template(args.output_path)
    download_tweet(args.tweet_url, output_template, args.audio_only)


if __name__ == "__main__":
    main()
