import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ingest.downloader import VideoDownloader, start_time_from_url


class FakeYoutubeDL:
    instances = []

    def __init__(self, options):
        self.options = options
        self.urls = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def download(self, urls):
        self.urls = urls
        for hook in self.options.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished"})
        Path(self.options["outtmpl"]).write_bytes(b"local mp4")


class TimestampTests(unittest.TestCase):
    def test_numeric_and_clock_timestamps(self):
        self.assertEqual(start_time_from_url("https://youtu.be/abcdefghijk?t=90"), 90)
        self.assertEqual(
            start_time_from_url("https://youtube.com/watch?v=abcdefghijk&t=1h2m3s"),
            3723,
        )
        self.assertEqual(start_time_from_url("https://youtu.be/abcdefghijk"), 0)


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.instances.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.downloader = VideoDownloader(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("ingest.downloader.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("ingest.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    def test_full_video_reports_progress(self, _which):
        progress = []
        path = self.downloader.download_segment(
            "abcdefghijk",
            0,
            10,
            "ignored-job-id",
            full_video=True,
            on_progress=lambda value, stage: progress.append((value, stage)),
        )

        self.assertEqual(Path(path).read_bytes(), b"local mp4")
        options = FakeYoutubeDL.instances[0].options
        self.assertNotIn("download_ranges", options)
        self.assertEqual(options["merge_output_format"], "mp4")
        self.assertIn("[ext=mp4]", options["format"])
        self.assertIn((0.5, "yt-dlp"), progress)
        self.assertEqual(progress[-1], (1.0, "downloaded"))

    @patch("ingest.downloader.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("ingest.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    def test_timestamped_link_uses_bounded_section_with_ffmpeg(self, _which):
        self.downloader.download_segment(
            "abcdefghijk", 120, 152, "ignored-job-id", full_video=False
        )

        options = FakeYoutubeDL.instances[0].options
        self.assertIn("download_ranges", options)
        self.assertTrue(options["force_keyframes_at_cuts"])
        self.assertEqual(options["merge_output_format"], "mp4")

    @patch("ingest.downloader.shutil.which", return_value=None)
    def test_download_explains_ffmpeg_requirement(self, _which):
        with self.assertRaisesRegex(RuntimeError, "ffmpeg is required"):
            self.downloader.download_segment(
                "abcdefghijk", 0, 10, "ignored-job-id", full_video=True
            )

    @patch("ingest.downloader.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("ingest.downloader.yt_dlp.YoutubeDL")
    def test_existing_segment_is_reused(self, youtube_dl, _which):
        expected = Path(self.temp_dir.name) / "abcdefghijk_00000_00010.mp4"
        expected.write_bytes(b"cached")

        actual = self.downloader.download_segment(
            "abcdefghijk", 0, 10, "ignored-job-id", full_video=True
        )

        self.assertEqual(actual, str(expected))
        youtube_dl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
