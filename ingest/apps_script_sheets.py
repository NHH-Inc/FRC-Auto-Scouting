"""Sheets export through a Google Apps Script web app, for accounts with Cloud disabled.

The existing exporter needs a Google Cloud service account. School Google Workspace accounts
routinely have Cloud console access switched off by an administrator, and no amount of code fixes
that -- the project simply cannot be created. That blocks the export on exactly the accounts the
team actually uses, because the sheet lives in the school account.

Apps Script goes around the problem rather than through it. A script bound to the spreadsheet runs
*as the signed-in owner*, inside Workspace, needing no Cloud project, no service account and no
credential file. It publishes a URL; this posts rows to it.

The important part is that the semantics are unchanged. Column A stays the stable key, a re-export
replaces a row rather than appending a duplicate, and the result reports rows_written and
rows_skipped exactly as the Cloud path does. Doc 3's rule that "Sheets is an export destination,
not storage" is unaffected: this is still a push of derived rows, and nothing is ever read back
as a source of truth.

The upsert happens inside the script rather than here, deliberately. Doing it client-side would
mean downloading the whole sheet, diffing, and uploading -- two round trips and a race if anyone
else is editing. One POST, and the script merges against the live sheet.

Security note: an Apps Script web app published for "anyone with the link" has no Google-level
auth, so the URL alone would let a stranger write to the sheet. A shared secret travels in the
POST body and the script refuses anything without it. The secret belongs in ingest/.env and must
never be committed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class AppsScriptExporter:
    """Same interface as SheetsExporter, different transport."""

    def __init__(
        self,
        url: str | None = None,
        secret: str | None = None,
        post=None,
        timeout: float = 30.0,
    ):
        self.url = url if url is not None else os.environ.get("APPS_SCRIPT_URL", "")
        self.secret = secret if secret is not None else os.environ.get("APPS_SCRIPT_SECRET", "")
        self.timeout = timeout
        #: Injected for tests, mirroring how the TBA client takes a fetch function. Nothing here
        #: should need a live web app to be exercised.
        self._post = post or self._urllib_post

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret)

    @property
    def spreadsheet_url(self) -> str:
        """Not derivable from the script URL; the script returns it so the UI can link out."""
        return getattr(self, "_last_spreadsheet_url", "")

    def _urllib_post(self, url: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        # Apps Script answers a POST with a 302 to googleusercontent.com; urllib follows it, but
        # only because the redirect is preserved as a GET-able result URL. Without following it
        # the caller sees an empty body and assumes failure.
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}

    def export(self, mode: str, headers: list, rows: list) -> dict:
        """Push rows to the script. Returns the same shape as the Cloud exporter."""
        if not self.configured:
            return {"rows_written": 0, "rows_skipped": len(rows), "configured": False}

        tab = "raw_events" if mode == "raw" else "aggregates"
        payload = {
            "secret": self.secret,
            "tab": tab,
            "headers": list(headers),
            # None is not valid JSON for a cell; the Cloud path blanks these too, so the two
            # transports produce identical sheets rather than subtly different ones.
            "rows": [["" if v is None else v for v in row] for row in rows],
        }

        try:
            result = self._post(self.url, payload)
        except urllib.error.HTTPError as error:
            return {"rows_written": 0, "rows_skipped": len(rows), "configured": True,
                    "error": f"apps script returned HTTP {error.code}"}
        except Exception as error:  # network, timeout, malformed JSON
            return {"rows_written": 0, "rows_skipped": len(rows), "configured": True,
                    "error": str(error)[:200]}

        if not result.get("ok"):
            # A wrong secret lands here. Reported rather than raised, so a misconfiguration shows
            # up as a clear message in the response instead of a stack trace.
            return {"rows_written": 0, "rows_skipped": len(rows), "configured": True,
                    "error": result.get("error", "apps script rejected the request")}

        self._last_spreadsheet_url = result.get("spreadsheet_url", "")
        return {
            "rows_written": int(result.get("rows_written", 0)),
            "rows_skipped": int(result.get("rows_skipped", 0)),
            "configured": True,
            "spreadsheet_url": self._last_spreadsheet_url,
        }
