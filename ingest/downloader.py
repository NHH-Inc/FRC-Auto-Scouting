import yt_dlp
import json
import os
from pathlib import Path

class VideoDownloader:
    def __init__(self, download_dir: str = "/data/segments"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def get_video_info(self, url: str):
        """Validates a link and returns metadata using --dump-json."""
        ydl_opts = {'quiet': True, 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info

    def download_segment(self, video_id: str, start_time: float, duration: float, job_id: str):
        """Downloads a specific section of a video."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_filename = f"{video_id}_{int(start_time)}_{int(start_time + duration)}.mp4"
        output_path = self.download_dir / output_filename

        end_time = start_time + duration

        # Format selection: cap at 1080p as per document
        ydl_opts = {
            'format': 'bv*[height<=1080]+ba/b[height<=1080]',
            'outtmpl': str(output_path),
            'download_sections': [{
                'start_time': start_time,
                'end_time': end_time,
                'title': f"Match Segment {job_id}"
            }],
            'force_keyframes_at_cuts': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        return str(output_path)
