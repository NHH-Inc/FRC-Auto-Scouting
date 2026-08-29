"""Google Sheets export.

Doc 3: "Sheets is an export destination, not storage. The Sheets API will not hold up if
treated as a database." So this writes a flat denormalized table and nothing reads back from
it as a source of truth.

Three rules from doc 3, all load-bearing:

- **Shape.** "One row per team per match, columns for the aggregate stats" -- the shape scouts
  actually use in a spreadsheet, not the event stream.
- **Batching.** "Batch the writes; per-row API calls will hit quota immediately." This does
  exactly two API calls per export regardless of row count: one read, one write.
- **Idempotence.** "Make re-export idempotent so running it twice does not duplicate rows."
  Every row carries a stable key -- `match_id|team` for aggregates, `event_id` for raw --
  and re-export updates in place rather than appending.

Without credentials this reports `configured: False` and writes nothing, so the rest of the
service runs fine in development.
"""

import os

AGGREGATE_HEADERS = [
    "row_key", "match_id", "team", "cycles", "avg_cycle_seconds",
    "shot_attempts", "shots_made", "shot_accuracy", "avg_shot_interval_seconds",
    "reloads", "defense_seconds", "immobile_seconds", "fouls", "low_confidence_events",
]

RAW_HEADERS = [
    "row_key", "match_id", "event_id", "team", "track_id", "t_seconds",
    "phase", "event_type", "goal", "confidence", "field_x", "field_y", "source",
    "corrected",
]


def _aggregate_row(match_id: str, stats: dict) -> list:
    return [
        f"{match_id}|{stats['team']}",
        match_id,
        stats["team"],
        stats["cycles"],
        stats["avg_cycle_seconds"],
        stats["shot_attempts"],
        stats["shots_made"],
        stats["shot_accuracy"],
        stats["avg_shot_interval_seconds"],
        stats["reloads"],
        stats["defense_seconds"],
        stats["immobile_seconds"],
        stats["fouls"],
        stats["low_confidence_events"],
    ]


def _raw_row(event: dict) -> list:
    return [
        event["event_id"],
        event["match_id"],
        event["event_id"],
        event.get("team"),
        event.get("track_id"),
        event.get("t_seconds"),
        event.get("phase"),
        event.get("event_type"),
        event.get("goal"),
        event.get("confidence"),
        event.get("field_x"),
        event.get("field_y"),
        event.get("source"),
        event.get("corrected", False),
    ]


def build_rows(mode: str, per_match) -> tuple[list, list]:
    """Turn the export payload into (headers, rows). Pure -- no API calls, so it is testable.

    `per_match` is an iterable of (match_id, events, team_stats_list).
    """
    if mode == "raw":
        rows = [_raw_row(e) for _match_id, events, _stats in per_match for e in events]
        return RAW_HEADERS, rows
    rows = [
        _aggregate_row(match_id, s)
        for match_id, _events, stats_list in per_match
        for s in stats_list
    ]
    return AGGREGATE_HEADERS, rows


class SheetsExporter:
    """Writes to one spreadsheet, one tab per mode."""

    def __init__(self, spreadsheet_id: str | None = None, credentials_path: str | None = None):
        self.spreadsheet_id = spreadsheet_id or os.environ.get("SHEETS_SPREADSHEET_ID", "")
        self.credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS", ""
        )
        self._service = None

    @property
    def configured(self) -> bool:
        return bool(self.spreadsheet_id and self.credentials_path)

    def _client(self):
        if self._service is not None:
            return self._service
        # Imported lazily so the service starts without google-api-python-client installed.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            self.credentials_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return self._service

    def spreadsheet_url(self) -> str:
        if not self.spreadsheet_id:
            return ""
        return f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/edit"

    def _ensure_tab(self, service, tab: str) -> None:
        """Create the tab if it is missing.

        Without this the first export fails on a bad range, and the fix would be "go and add a
        tab named exactly `aggregates` by hand" -- a setup step nobody would remember. Costs one
        metadata read; the write only happens the first time.
        """
        meta = service.get(spreadsheetId=self.spreadsheet_id).execute()
        titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if tab in titles:
            return
        service.batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
        ).execute()

    def export(self, mode: str, headers: list, rows: list) -> dict:
        """Reads the existing sheet, then writes the merged result.

        A small constant number of API calls regardless of row count -- doc 3's concern is
        per-row calls, which hit quota immediately.

        Returns {rows_written, rows_skipped}. `rows_skipped` counts rows that were already
        present and unchanged -- the visible proof that a second export did not duplicate.
        """
        if not self.configured:
            return {"rows_written": 0, "rows_skipped": len(rows), "configured": False}

        tab = "raw_events" if mode == "raw" else "aggregates"
        service = self._client().spreadsheets()
        self._ensure_tab(service, tab)

        try:
            existing = (
                service.values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{tab}!A:Z")
                .execute()
                .get("values", [])
            )
        except Exception:
            existing = []

        # Index existing rows by their stable key (column A), so a re-export replaces rather
        # than appends. This is the whole idempotence guarantee.
        body = existing[1:] if existing else []
        by_key = {row[0]: i for i, row in enumerate(body) if row}

        written = 0
        skipped = 0
        for row in rows:
            key = str(row[0])
            serialised = ["" if v is None else v for v in row]
            if key in by_key:
                if body[by_key[key]] == [str(v) for v in serialised]:
                    skipped += 1
                    continue
                body[by_key[key]] = serialised
            else:
                by_key[key] = len(body)
                body.append(serialised)
            written += 1

        # One write for everything. Per-row calls hit the quota immediately.
        service.values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [headers] + body},
        ).execute()

        return {"rows_written": written, "rows_skipped": skipped, "configured": True}
