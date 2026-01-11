# Video Tools

Small scripts for generating overlays/thumbnails and downloading videos.

Notes:
- `output/` is gitignored and used for test assets and default outputs.
- Most scripts assume `ffmpeg`/`ffprobe` and Python packages are installed.

## Overlay tools

Create an overlay PNG and apply it to a video.

```bash
python overlay.py input.mp4 output.mp4 "Left text" "Right text"
python overlay.py -t 1920 1080 "Left text" output/overlay.png "Right text"
```

Generate an overlay PNG directly:
```bash
python generate_overlay.py 1920 1080 "Left text" output/overlay.png "Right text"
python generate_overlay.py -t
```

Apply an existing overlay PNG:
```bash
python apply_overlay.py input.mp4 overlay.png output.mp4
```

## Thumbnails

Generate a 1920x1080 thumbnail with auto-sized text:
```bash
python thumbnail.py "Main Title" "Sub text"
python thumbnail.py "Main Title" "Sub text" /path/to/custom.png
python thumbnail.py -t
python thumbnail.py -e
```

Test mode creates `output/test_thumbnail_N/` with multiple random samples.

## Unified downloader

Download from YouTube, Twitch, or Twitter/X with one script:
```bash
python download_video.py "https://www.youtube.com/watch?v=VIDEO_ID"
python download_video.py "https://www.twitch.tv/videos/123456789" output/
python download_video.py "https://x.com/user/status/1234567890" output/%(title)s.%(ext)s
python download_video.py "https://www.youtube.com/watch?v=VIDEO_ID" --audio-only
```

`download_video.py` dispatches to `yt_downloader.py`, `twitch_downloader.py`,
or `twitter_downloader.py` based on the URL.

## YouTube downloader

Download a YouTube video using yt-dlp:
```bash
python yt_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"
python yt_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" output/
python yt_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" output/%(title)s.%(ext)s
python yt_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID" --audio-only
```

`output_path` can be a directory or a full yt-dlp output template. If you pass
`output/` (or any existing directory), files are saved as `%(title)s.%(ext)s`.
If you pass a file/template, it is used as-is. The default is the current
working directory.

yt-dlp install/update:
```bash
pipx install yt-dlp
pipx upgrade yt-dlp
yt-dlp -U
sudo apt install yt-dlp
```

If you see `nsig extraction failed`, update yt-dlp.

## Twitch downloader

```bash
python twitch_downloader.py https://www.twitch.tv/videos/123456789
python twitch_downloader.py https://www.twitch.tv/videos/123456789 output/
python twitch_downloader.py https://www.twitch.tv/videos/123456789 output/vod.mp4
python twitch_downloader.py https://www.twitch.tv/videos/123456789 --audio-only
```

`output_path` can be a directory or a file/template. If you pass a directory,
files are saved as `twitch_<id>.mp4`. Templates support yt-dlp placeholders
like `%(id)s`.

## Twitter/X downloader

`twitter_downloader.py` uses yt-dlp. Optional `.env` override:
```
YT_DLP_PATH=/path/to/yt-dlp
```

Run it:
```bash
python twitter_downloader.py "https://x.com/user/status/1234567890"
python twitter_downloader.py "https://x.com/user/status/1234567890" output/
python twitter_downloader.py "https://x.com/user/status/1234567890" output/tweet.mp4
python twitter_downloader.py "https://x.com/user/status/1234567890" --audio-only
```

`output_path` can be a directory or a file/template. If you pass a directory,
files are saved as `tweet_<id>.mp4`. Audio-only writes `.m4a` and requires
`ffmpeg`.
