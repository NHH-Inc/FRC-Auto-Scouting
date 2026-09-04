"""The Apps Script export transport, exercised without a live web app.

The HTTP call is injected, so everything the exporter decides -- payload shape, refusal when
unconfigured, how failures are reported -- is testable offline. A transport that can only be
tested by writing to a real spreadsheet gets tested once and never again.
"""

import unittest

from ingest.apps_script_sheets import AppsScriptExporter

HEADERS = ["key", "match", "team", "points"]
ROWS = [["2026x_qm1|254", "2026x_qm1", 254, 30], ["2026x_qm1|1678", "2026x_qm1", 1678, None]]


class Recorder:
    """Captures the posted payload and returns a scripted reply."""

    def __init__(self, reply=None, raise_with=None):
        self.reply = reply if reply is not None else {
            "ok": True, "rows_written": 2, "rows_skipped": 0,
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/abc/edit",
        }
        self.raise_with = raise_with
        self.url = None
        self.payload = None

    def __call__(self, url, payload):
        self.url, self.payload = url, payload
        if self.raise_with:
            raise self.raise_with
        return self.reply


class ConfigurationTests(unittest.TestCase):
    def test_unconfigured_reports_itself_rather_than_pretending(self):
        e = AppsScriptExporter(url="", secret="")
        result = e.export("aggregate", HEADERS, ROWS)
        self.assertFalse(result["configured"])
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(result["rows_skipped"], len(ROWS))

    def test_a_url_without_a_secret_is_not_configured(self):
        # Posting to an open web app with no secret would let anyone write to the sheet.
        e = AppsScriptExporter(url="https://script.google.com/x/exec", secret="")
        self.assertFalse(e.configured)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.post = Recorder()
        self.exporter = AppsScriptExporter(
            url="https://script.google.com/x/exec", secret="s3cret", post=self.post)

    def test_the_secret_travels_with_the_request(self):
        self.exporter.export("aggregate", HEADERS, ROWS)
        self.assertEqual(self.post.payload["secret"], "s3cret")

    def test_mode_selects_the_tab(self):
        self.exporter.export("raw", HEADERS, ROWS)
        self.assertEqual(self.post.payload["tab"], "raw_events")
        self.exporter.export("aggregate", HEADERS, ROWS)
        self.assertEqual(self.post.payload["tab"], "aggregates")

    def test_none_becomes_blank_so_both_transports_write_the_same_sheet(self):
        self.exporter.export("aggregate", HEADERS, ROWS)
        self.assertEqual(self.post.payload["rows"][1][3], "")

    def test_counts_come_back_from_the_script(self):
        result = self.exporter.export("aggregate", HEADERS, ROWS)
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(result["rows_skipped"], 0)
        self.assertTrue(result["configured"])

    def test_the_spreadsheet_url_is_surfaced(self):
        # Not derivable from the script URL, so the script has to tell us.
        result = self.exporter.export("aggregate", HEADERS, ROWS)
        self.assertIn("docs.google.com", result["spreadsheet_url"])


class FailureTests(unittest.TestCase):
    def _exporter(self, **kw):
        return AppsScriptExporter(url="https://script.google.com/x/exec", secret="s",
                                  post=Recorder(**kw))

    def test_a_rejected_secret_is_reported_not_raised(self):
        e = self._exporter(reply={"ok": False, "error": "rejected"})
        result = e.export("aggregate", HEADERS, ROWS)
        self.assertEqual(result["rows_written"], 0)
        self.assertIn("rejected", result["error"])

    def test_a_network_failure_does_not_look_like_a_successful_write(self):
        e = self._exporter(raise_with=TimeoutError("timed out"))
        result = e.export("aggregate", HEADERS, ROWS)
        self.assertEqual(result["rows_written"], 0)
        self.assertEqual(result["rows_skipped"], len(ROWS))
        self.assertIn("timed out", result["error"])


if __name__ == "__main__":
    unittest.main()
