#!/usr/bin/env python3
import textwrap


def main():
    message = """
+--------------------------------------------------------------------------+
|                            VIDEO TOOLS INDEX                             |
+--------------------------------------------------------------------------+

+--------------------------------------------------------------------------+
| OVERVIEW                                                                 |
+--------------------------------------------------------------------------+
| A collection of small CLI scripts for video overlays, thumbnails, and    |
| downloading media from YouTube/Twitch/Twitter(X). Most scripts write to  |
| ./output by default and can be pointed elsewhere when needed.            |
+--------------------------------------------------------------------------+

+--------------------------------------------------------------------------+
| DEPENDENCIES                                                             |
+--------------------------------------------------------------------------+
| ffmpeg/ffprobe: overlay.py, apply_overlay.py, accurate_slice.py          |
| Pillow:          overlay + thumbnail tools                               |
| yt-dlp:          download_video.py, yt_downloader.py,                    |
|                 twitter_downloader.py, twitch_downloader.py              |
| .env optional:  twitter_downloader.py supports YT_DLP_PATH override      |
+--------------------------------------------------------------------------+

+--------------------------------------------------------------------------+
| TOOLS                                                                    |
+--------------------------------------------------------------------------+
| overlay.py                                                               |
|   Master overlay tool. Creates a temporary overlay PNG and applies it    |
|   to a video with ffmpeg. For direct PNG generation or manual overlay    |
|   application, see generate_overlay.py and apply_overlay.py.             |
|   Usage: python overlay.py input.mp4 output.mp4 "Left" "Right"           |
|   Test:  python overlay.py -t 1920 1080 "Left" output/overlay.png        |
|                                                                          |
| thumbnail.py                                                             |
|   Generate thumbnails at any size with auto-sized text.                  |
|   Usage: python thumbnail.py "Main" "Sub" [output.png]                   |
|   Test:  python thumbnail.py -t                                          |
|                                                                          |
| accurate_slice.py                                                        |
|   Frame-accurate slicing by transcoding to an intraframe intermediate.   |
|   Usage: python accurate_slice.py input.mp4 output.mp4 0:10 0:15         |
|                                                                          |
| download_video.py                                                        |
|   Auto-detects YouTube/Twitch/Twitter(X) and dispatches to the           |
|   download scripts: yt_downloader.py, twitter_downloader.py,             |
|   twitch_downloader.py.                                                  |
|   Usage: python download_video.py URL [output_dir_or_template]           |
|   Audio: python download_video.py URL --audio-only                       |
+--------------------------------------------------------------------------+

"""

    print(textwrap.dedent(message).strip())


if __name__ == "__main__":
    main()
