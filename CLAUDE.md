# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Collection of standalone Python CLI scripts for video overlays, thumbnails, and downloading media from YouTube/Twitch/Twitter(X). No build system, no test framework — each script runs directly with `python <script>.py`.

## External Dependencies

- **ffmpeg/ffprobe**: Used by overlay tools, `apply_overlay.py`, and `accurate_slice.py`
- **Pillow**: Used by overlay and thumbnail image generation (`generate_overlay.py`, `thumbnail.py`)
- **yt-dlp**: Used by all downloaders. Install via `pipx install yt-dlp`
- **Flask**: Optional, only needed for `slice_ui.py`. Install via `pip install flask`
- **Font**: `assets/cour_bold.ttf` (Courier Bold) is required by overlay/thumbnail generation

## Architecture

### Overlay pipeline (3 scripts, composable)
- `overlay.py` — Orchestrator: gets video dimensions via ffprobe, generates a temp overlay PNG, then applies it. Imports from both scripts below.
- `generate_overlay.py` — Creates a transparent RGBA PNG with text labels at bottom-left and optionally bottom-right. Exports `create_text_overlay()`.
- `apply_overlay.py` — Composites a PNG onto a video with ffmpeg. Exports `apply_overlay()`.

### Accurate slice pipeline (`accurate_slice.py` + `slice_tools/`)
Frame-accurate video slicing using boundary re-encode: only ~4s chunks around each cut point are re-encoded through an intraframe intermediate (ffv1), while the bulk of the clip is stream-copied (fast, zero quality loss). Short clips (<4s) use a single-region re-encode path.
- `slice_tools/timecode.py` — Parses `ss`, `mm:ss`, `hh:mm:ss` formats to seconds
- `slice_tools/ffmpeg_utils.py` — Shared helpers: `run_cmd()`, `has_audio()`, `probe_stream_types()`, `probe_video_info()`, `probe_duration()`
- `slice_tools/slice_ops.py` — Two cut engines:
  - `accurate_cut()` — accurate seek (`-ss` before `-i`) + full re-encode of the span. **Exactly** frame-accurate; the slower but correct option, and what `slice_ui.py` uses by default.
  - `boundary_slice()` — the fast path. Because the bulk is stream-copied, the cut snaps to keyframes and the output can run ~2 frames long. Only use where that slop is acceptable.
  - Helpers: `build_encoder_args()`, `stream_copy_segment()`, `cut_and_encode_segment()`, `concat_segments()`. Legacy `convert_to_intraframe()` and `slice_precise()` still present.

### Slice web UI (`slice_ui.py`)
Browser-based clip editor. Flask backend + single-page app: browse local files, preview in an HTML5 player, set start/end on a waveform timeline, and cut. Async via threading, SSE for progress. **Cuts save next to the source file** (`resolve_output_dir()`), falling back to `output/` for sources inside `.uploads/`/`.working_copies/` or on read-only mounts.
- `templates/slice.html` — Single HTML template with inline CSS/JS (dark theme, vanilla JS, no build tools). Timeline/trim UI is ported from the `clipmine` project.
- **Preview windows** (`GET /media/window?path=&idx=`): browsers can't decode HEVC. Rather than transcoding a whole 45-min episode up front, the preview is built as 60s H.264 blocks on demand (NVENC, libx264 fallback), grid-aligned and cached in `.working_copies/windows/`. Opening or seeking anywhere costs ~2s instead of ~60s. Blocks carry 2s of overlap and the next one is prefetched, so playback crosses boundaries without stalling.
  - `-ss` precedes `-i` in the block build, so block time 0 is **exactly** `idx * WINDOW_SEC` in the source. The frontend adds that offset back (`regionStartMs`) — the timeline always spans the whole file. Verified by frame comparison (38.6 dB PSNR aligned vs 13.8 dB one second off); if you change the build command, re-check this.
  - Browser-playable files (h264/mp4 etc.) skip all of this and stream the original directly.
  - **Preview only — cuts always run on the original file at full quality.**
- `GET /media/wave` — `showwavespic` PNG behind the timeline, cached in `.working_copies/waves/`.
- `POST /api/snapcuts` — snaps a trim edge to the nearest scene cut (ffmpeg `select='gt(scene,N)'`), landing one frame *inside* the cut to avoid a flash of the neighbouring shot.
- `POST /api/slice` takes `mode`: `accurate` (default) or `fast`.
- `POST /api/locate` — a browser drop exposes a blob, not a path. Rather than uploading gigabytes, the server finds the file on disk by name+size and loads it in place. `/api/upload` is the fallback for files that genuinely aren't local.

### Download dispatcher
- `download_video.py` — Regex-based URL detection, dispatches to the appropriate downloader via subprocess
- `yt_downloader.py`, `twitch_downloader.py`, `twitter_downloader.py`, `instagram_downloader.py` — Each wraps yt-dlp with platform-specific defaults and output template handling
- `twitter_downloader.py` has its own `.env` loader for `YT_DLP_PATH` override
- `instagram_downloader.py` handles `/p/`, `/tv/`, `/reel/`, `/reels/` URLs (with optional `username/` prefix); default filename appends the shortcode id since IG titles aren't unique

### Thumbnail generator (`thumbnail.py`)
Generates 1920x1080 PNGs with auto-scaled text using binary search for optimal font size. Has test mode (`-t`) that creates 30 random samples and empty mode (`-e`).

## Conventions

- All scripts use `argparse` or manual `sys.argv` parsing with `-h`/`--help` support
- Test/preview modes are invoked with `-t`/`--test` flags (no test framework)
- Default output goes to `output/` (gitignored)
- Dimension scaling throughout uses a `scale_value(base, scale)` pattern relative to 1920x1080 base resolution
- `.env` file in repo root is gitignored
