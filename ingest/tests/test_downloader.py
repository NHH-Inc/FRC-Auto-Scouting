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

    def extract_info(self, url, download=False):
        self.urls = [url]
        return {
            "requested_formats": [
                {
                    "url": "https://media.example/video.mp4?signature=test",
                    "protocol": "https",
                    "format_id": "136",
                    "vcodec": "avc1",
                    "acodec": "none",
                    "http_headers": {"User-Agent": "yt-dlp-test"},
                },
                {
                    "url": "https://media.example/audio.m4a?signature=test",
                    "protocol": "https",
                    "format_id": "140",
                    "vcodec": "none",
                    "acodec": "mp4a",
                    "http_headers": {"User-Agent": "yt-dlp-test"},
                },
            ],
        }


class FakeCombinedYoutubeDL(FakeYoutubeDL):
    def extract_info(self, url, download=False):
        self.urls = [url]
        return {
            "url": "https://media.example/combined.mp4?signature=test",
            "protocol": "https",
            "format_id": "22",
            "ext": "mp4",
            "vcodec": "avc1",
            "acodec": "mp4a",
        }


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

    @patch("ingest.downloader.shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("ingest.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    def test_live_capture_records_to_its_own_file_from_start(self, _which):
        path = self.downloader.capture_live("abcdefghijk", "live-job")

        options = FakeYoutubeDL.instances[0].options
        self.assertEqual(Path(path).read_bytes(), b"local mp4")
        self.assertIn("live_live-job", path)
        self.assertTrue(options["live_from_start"])
        self.assertNotIn("download_ranges", options)
        self.assertEqual(options["merge_output_format"], "mp4")

    @patch("ingest.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL)
    def test_stream_resolver_selects_one_video_audio_file_and_caches_it(self):
        first = self.downloader.resolve_stream("abcdefghijk")
        second = self.downloader.resolve_stream("abcdefghijk")

        self.assertEqual(first["video"]["url"], "https://media.example/video.mp4?signature=test")
        self.assertEqual(first["audio"]["url"], "https://media.example/audio.m4a?signature=test")
        self.assertEqual(second, first)
        self.assertEqual(len(FakeYoutubeDL.instances), 1)
        self.assertIn("vcodec^=avc1", FakeYoutubeDL.instances[0].options["format"])

    @patch("ingest.downloader.yt_dlp.YoutubeDL", FakeCombinedYoutubeDL)
    def test_stream_resolver_reuses_combined_format_for_hidden_audio(self):
        resolved = self.downloader.resolve_stream("abcdefghijk")

        self.assertEqual(resolved["video"]["url"], resolved["audio"]["url"])
        self.assertEqual(resolved["audio"]["content_type"], "audio/mp4")


if __name__ == "__main__":
    unittest.main()
