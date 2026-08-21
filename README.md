# Video Tools

A collection of standalone CLI scripts (plus one web app) for video overlays,
thumbnails, frame-accurate slicing, and downloading media from YouTube, Twitch,
Twitter/X, and Instagram. Each script runs directly — no build step.

## Tools at a glance

| Tool | What it does |
|------|--------------|
| `slice_ui.py` | **Browser clip editor** — preview any file, set start/end on a waveform timeline, and cut. Frame-accurate, GPU-accelerated, GIF export, audio-track picker. |
| `accurate_slice.py` | Frame-accurate slice from the command line. |
| `overlay.py` | Add bottom-left / bottom-right text captions to a video. |
| `generate_overlay.py` | Build just the transparent overlay PNG. |
| `apply_overlay.py` | Composite an existing overlay PNG onto a video. |
| `thumbnail.py` | Generate a 1920×1080 thumbnail with auto-sized text. |
| `download_video.py` | **Unified downloader** — detects the platform and dispatches. |
| `yt_downloader.py` | YouTube (via yt-dlp). |
| `twitch_downloader.py` | Twitch VODs. |
| `twitter_downloader.py` | Twitter/X posts. |
| `instagram_downloader.py` | Instagram posts, reels, and TV. |
| `index.py` | Prints this list of tools in the terminal. |

## Requirements

- **ffmpeg / ffprobe** — slicing, overlays, downloads
- **Pillow** — overlay and thumbnail image generation
- **yt-dlp** — all downloaders (`pipx install yt-dlp`)
- **Flask** — only for `slice_ui.py` (`pip install flask`)
- `assets/cour_bold.ttf` — font used by overlays and thumbnails

`output/` is gitignored and used for default outputs and test assets.

## Clip editor (`slice_ui.py`)

A browser-based editor: browse local files, scrub on a waveform timeline, set an
in/out selection, and cut it — saved next to the source file at full quality.

```bash
python slice_ui.py            # serves on http://127.0.0.1:5000
python slice_ui.py -p 5055    # custom port
```

- **Preview** builds short H.264 blocks on demand, so a 45-minute HEVC file opens
  in ~2s instead of transcoding up front. Cuts always run on the original.
- **Cut modes**: frame-accurate (default), fast (keyframe-snapped), or GIF export.
- **Audio-track picker** appears for multi-track files (e.g. screen recordings
  with separate mic/desktop tracks); the cut follows the track you pick.
- Jump straight to a file with `?path=/abs/path/to/video.mp4`.

## Command-line slice (`accurate_slice.py`)

```bash
python accurate_slice.py input.mp4 output.mp4 00:01:10 00:01:35
python accurate_slice.py input.mov output.mp4 1:10 1:35.5
```

Time format: `ss`, `mm:ss`, or `hh:mm:ss` (fractions allowed in the seconds).

## Overlays

```bash
# One shot: generate the overlay PNG and apply it
python overlay.py input.mp4 output.mp4 "Left text" "Right text"

# Generate just the PNG
python generate_overlay.py 1920 1080 "Left text" output/overlay.png "Right text"

# Apply an existing PNG
python apply_overlay.py input.mp4 overlay.png output.mp4
```

Add `-t` to `overlay.py` / `generate_overlay.py` for a test render.

## Thumbnails

```bash
python thumbnail.py "Main Title" "Sub text"
python thumbnail.py "Main Title" "Sub text" /path/to/custom.png
python thumbnail.py -t    # 30 random samples in output/
python thumbnail.py -e    # empty template
```

## Downloaders

Use the unified dispatcher, or call a platform script directly — they share the
same arguments.

```bash
python download_video.py "https://www.youtube.com/watch?v=VIDEO_ID"
python download_video.py "https://www.twitch.tv/videos/123456789" output/
python download_video.py "https://x.com/user/status/1234567890"
python download_video.py "https://www.instagram.com/reel/SHORTCODE/"
python download_video.py "<url>" --audio-only
```

**Output path** (second argument, optional): pass a directory to save as
`%(title)s.%(ext)s` (Twitch/Twitter fall back to `<platform>_<id>.mp4`), or pass
a file / yt-dlp template to use it as-is. Defaults to the current directory.

Twitter/X honors a `YT_DLP_PATH` override in a repo-root `.env` file.

### Updating yt-dlp

Most download failures (`nsig extraction failed`, empty responses, "sign in to
confirm") are fixed by updating:

```bash
pipx upgrade yt-dlp    # or: yt-dlp -U
```

Age-restricted or hardened videos may also need browser cookies
(`--cookies-from-browser firefox`) and a JavaScript runtime
(`--js-runtimes node`) passed to yt-dlp directly.
