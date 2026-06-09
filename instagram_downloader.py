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


def ensure_yt_dlp() -> str:
    yt_dlp_path = shutil.which("yt-dlp")
    if not yt_dlp_path:
        print("Error: yt-dlp not found in PATH.", file=sys.stderr)
        print(UPDATE_INSTRUCTIONS, file=sys.stderr)
        sys.exit(1)
    return yt_dlp_path


def resolve_output_template(output_path: str | None) -> tuple[str, str]:
    # Instagram "titles" are often just "Video by <user>", so include the
    # shortcode id to keep filenames unique.
    default_name = "%(title).80B [%(id)s].%(ext)s"
    if not output_path:
        cwd = os.getcwd()
        return os.path.join(cwd, default_name), cwd

    expanded = os.path.expanduser(output_path)
    ends_with_sep = expanded.endswith(os.path.sep) or expanded.endswith("/")
    is_template = "%(" in expanded
    has_extension = os.path.splitext(expanded)[1] != ""

    if os.path.isdir(expanded) or ends_with_sep or (not is_template and not has_extension):
        os.makedirs(expanded, exist_ok=True)
        return os.path.join(expanded, default_name), expanded

    output_dir = os.path.dirname(expanded)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    return expanded, output_dir or os.getcwd()


def download_video(instagram_url: str, output_template: str, audio_only: bool) -> None:
    """Download an Instagram reel/post/video using yt-dlp."""
    yt_dlp_path = ensure_yt_dlp()
    cmd = [
        yt_dlp_path,
        "-o",
        output_template,
    ]
    if audio_only:
        cmd += ["-f", "ba/best"]
    else:
        cmd += ["-f", "bv*+ba/best"]

    cmd.append(instagram_url)

    try:
        print(f"Downloading: {instagram_url}")
        subprocess.run(
            cmd,
            check=True,
            text=True
        )
        print(f"Downloaded successfully to {output_template}")
    except subprocess.CalledProcessError as e:
        print(f"Error: yt-dlp failed with error code {e.returncode}. Details: {e.stderr or e.stdout}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download an Instagram reel/post/video using yt-dlp.",
        epilog=UPDATE_INSTRUCTIONS
        + "\nNote: Private/age-gated posts may require cookies (yt-dlp --cookies-from-browser).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("instagram_url", help="Instagram reel/post/video URL")
    parser.add_argument(
        "output_path",
        nargs="?",
        help="Output directory or file template (default: current directory).",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download audio only (best available audio).",
    )
    args = parser.parse_args()

    output_template, _ = resolve_output_template(args.output_path)

    download_video(args.instagram_url, output_template, args.audio_only)
