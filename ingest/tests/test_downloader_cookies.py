"""How yt-dlp is told who we are, and how a bot check is reported.

YouTube's "Sign in to confirm you're not a bot" is intermittent gating, not a broken download.
Classifying it as download_failed made the UI offer an immediate retry that could never work.
"""

import pytest

from ingest.downloader import apply_cookies
from ingest.main import _classify


@pytest.fixture(autouse=True)
def clear_cookie_env(monkeypatch):
    monkeypatch.delenv("YTDLP_COOKIES_FILE", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)


class TestApplyCookies:
    def test_nothing_configured_adds_nothing(self):
        # The common case is no cookies at all, and it must stay that way -- passing an empty
        # cookie source makes yt-dlp fail rather than fall back to anonymous.
        opts = {"quiet": True}
        assert apply_cookies(opts) == {"quiet": True}

    def test_a_cookie_file_is_used(self, monkeypatch):
        monkeypatch.setenv("YTDLP_COOKIES_FILE", "C:/cookies.txt")
        assert apply_cookies({})["cookiefile"] == "C:/cookies.txt"

    def test_a_browser_is_passed_as_the_tuple_yt_dlp_wants(self, monkeypatch):
        monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
        assert apply_cookies({})["cookiesfrombrowser"] == ("firefox",)

    def test_the_file_wins_when_both_are_set(self, monkeypatch):
        # On Windows the browser option cannot read Chrome at all (app-bound DPAPI), so someone
        # who has set both has almost certainly added the file because the browser failed.
        monkeypatch.setenv("YTDLP_COOKIES_FILE", "C:/cookies.txt")
        monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "chrome")
        opts = apply_cookies({})
        assert opts["cookiefile"] == "C:/cookies.txt"
        assert "cookiesfrombrowser" not in opts

    def test_it_does_not_disturb_the_other_options(self, monkeypatch):
        monkeypatch.setenv("YTDLP_COOKIES_FILE", "C:/cookies.txt")
        opts = apply_cookies({"quiet": True, "format": "bv*+ba"})
        assert opts["quiet"] is True and opts["format"] == "bv*+ba"


class TestClassify:
    def test_the_bot_check_is_gating_not_a_failed_download(self):
        # The real message, which contains "yt-dlp" only inside a help URL -- that incidental
        # substring is what used to route it to download_failed.
        message = ("ERROR: [youtube] M7lc1UVf-VE: Sign in to confirm you're not a bot. Use "
                   "--cookies-from-browser or --cookies for the authentication. See "
                   "https://github.com/yt-dlp/yt-dlp/wiki/FAQ for how to pass cookies")
        assert _classify(Exception(message)) == "rate_limited"

    def test_an_ordinary_download_failure_still_reads_as_one(self):
        assert _classify(Exception("yt-dlp: unable to download video data")) == "download_failed"

    def test_a_missing_video_is_not_gating(self):
        assert _classify(Exception("Video unavailable")) == "video_unavailable"

    def test_an_explicit_rate_limit_is_unchanged(self):
        assert _classify(Exception("HTTP Error 429: Too Many Requests")) == "rate_limited"
