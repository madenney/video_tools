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
- `slice_tools/slice_ops.py` — `boundary_slice()` orchestrator, plus helpers: `build_encoder_args()`, `stream_copy_segment()`, `cut_and_encode_segment()`, `concat_segments()`. Legacy `convert_to_intraframe()` and `slice_precise()` still present.

### Slice web UI (`slice_ui.py`)
Browser-based interface for the accurate slice pipeline. Flask backend serves a single-page app that lets you browse local video files, preview them in an HTML5 player, grab timecodes from the current playback position, and trigger `boundary_slice()` jobs. Async via threading, SSE for progress updates. Output goes to `output/`.
- `templates/slice.html` — Single HTML template with inline CSS/JS (dark theme, vanilla JS, no build tools)

### Download dispatcher
- `download_video.py` — Regex-based URL detection, dispatches to the appropriate downloader via subprocess
- `yt_downloader.py`, `twitch_downloader.py`, `twitter_downloader.py` — Each wraps yt-dlp with platform-specific defaults and output template handling
- `twitter_downloader.py` has its own `.env` loader for `YT_DLP_PATH` override

### Thumbnail generator (`thumbnail.py`)
Generates 1920x1080 PNGs with auto-scaled text using binary search for optimal font size. Has test mode (`-t`) that creates 30 random samples and empty mode (`-e`).

## Conventions

- All scripts use `argparse` or manual `sys.argv` parsing with `-h`/`--help` support
- Test/preview modes are invoked with `-t`/`--test` flags (no test framework)
- Default output goes to `output/` (gitignored)
- Dimension scaling throughout uses a `scale_value(base, scale)` pattern relative to 1920x1080 base resolution
- `.env` file in repo root is gitignored
