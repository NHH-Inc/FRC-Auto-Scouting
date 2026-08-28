"""yt-dlp wrapper.

Doc 2: "yt-dlp breaks regularly when YouTube changes things. Do not pin an old version...
treat a failed download as an expected condition, not a crash."
"""

from pathlib import Path

import yt_dlp
from yt_dlp.utils import download_range_func


class VideoDownloader:
    def __init__(self, download_dir: str = "/data/segments"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def get_video_info(self, url: str) -> dict:
        """Validates a link and returns metadata without fetching media (--dump-json)."""
        ydl_opts = {"quiet": True, "noplaylist": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def download_segment(
        self, video_id: str, start_time: float, duration: float, job_id: str
    ) -> str:
        """Downloads just the window containing the match.

        Doc 2: most official footage is a multi-hour VOD, and pulling only the relevant window
        "turns a six-hour download into a three-minute one and is essential for anything
        resembling scale."
        """
        url = f"https://www.youtube.com/watch?v={video_id}"
        end_time = start_time + duration
        output_path = self.download_dir / f"{video_id}_{int(start_time)}_{int(end_time)}.mp4"

        # Caching: doc 2 says never process the same segment twice, and the filename is keyed
        # by video id plus window, so an existing file is exactly the segment we want.
        if output_path.exists() and output_path.stat().st_size > 0:
            return str(output_path)

        ydl_opts = {
            # Cap the resolution rather than taking best: 1080p is plenty for detection and
            # 4K wastes bandwidth and decode time.
            "format": "bv*[height<=1080]+ba/b[height<=1080]",
            "outtmpl": str(output_path),
            "noplaylist": True,
            "quiet": True,
            "merge_output_format": "mp4",
            # The Python API takes a callable here. `download_sections` is the CLI spelling
            # and is ignored when passed as an option dict, which silently downloads the
            # ENTIRE video -- hours of it, for a two-minute match.
            "download_ranges": download_range_func([], [(start_time, end_time)]),
            "force_keyframes_at_cuts": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not output_path.exists():
            raise RuntimeError(f"yt-dlp reported success but {output_path.name} is missing")

        return str(output_path)
