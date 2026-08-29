"""The Blue Alliance client.

Doc 1: "Bumper color gives alliance reliably, which cuts the candidate set to three. TBA
supplies the three teams per alliance for a given match, so the search space is tiny." That
is what makes robot identification tractable, so this is not optional infrastructure.

Doc 1 again: "TBA is also the accuracy check. If the pipeline's reconstructed score does not
match TBA's official score for the same match, the pipeline is wrong. That comparison is the
main evaluation loop." Without `tba_score` there is nothing to evaluate against.

**The frc prefix is stripped here.** Doc 0: "TBA returns them as frc254; strip the prefix at
the ingest boundary so nothing downstream ever sees it." This module is that boundary.

Set TBA_API_KEY to enable. Without a key every call returns None and jobs still run -- doc 0
allows `alliances: null` and component 1 falls back to raw OCR without elimination, so a
missing key degrades the pipeline rather than breaking it.
"""

import os
import re
from typing import Callable

import requests

TBA_BASE = "https://www.thebluealliance.com/api/v3"
MATCH_KEY = re.compile(r"^[0-9]{4}[a-z0-9]+_[a-z0-9]+$")


def strip_team_prefix(team_key: str) -> int | None:
    """`frc254` -> `254`. Doc 0: integers everywhere, no leading zeros, no prefix."""
    if not isinstance(team_key, str):
        return None
    m = re.fullmatch(r"frc(\d+)", team_key.strip())
    return int(m.group(1)) if m else None


def event_key_of(match_id: str) -> str | None:
    """`2026casf_qm42` -> `2026casf`."""
    if not MATCH_KEY.match(match_id or ""):
        return None
    return match_id.split("_", 1)[0]


class TBAClient:
    """Thin, cached read-only client. Only the two calls the pipeline actually needs."""

    def __init__(self, api_key: str | None = None, fetch: Callable | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("TBA_API_KEY", "")
        # Injectable so tests never touch the network.
        self._fetch = fetch or self._http_get
        self._cache: dict[str, dict | None] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _http_get(self, path: str) -> dict | None:
        response = requests.get(
            f"{TBA_BASE}{path}",
            headers={"X-TBA-Auth-Key": self.api_key, "Accept": "application/json"},
            timeout=15,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_match(self, match_id: str) -> dict | None:
        """Raw TBA match object, or None when there is no data (or no API key)."""
        if not self.enabled or not MATCH_KEY.match(match_id or ""):
            return None
        if match_id in self._cache:
            return self._cache[match_id]
        try:
            data = self._fetch(f"/match/{match_id}")
        except Exception:
            # Doc 2's posture: an upstream that is down is an expected condition. A job with
            # alliances: null is still valid.
            data = None
        self._cache[match_id] = data
        return data

    def alliances_and_score(self, match_id: str) -> tuple[dict | None, dict | None]:
        """Returns (alliances, tba_score) in Contract A's shape, or (None, None).

        Contract A wants exactly three teams per side. A match with surrogates or a missing
        side is returned as None rather than a partial list, because component 1 uses this
        for process-of-elimination and a wrong candidate set is worse than no candidate set.
        """
        match = self.get_match(match_id)
        if not match:
            return None, None

        raw = match.get("alliances") or {}
        red, blue = raw.get("red") or {}, raw.get("blue") or {}

        red_teams = [t for t in (strip_team_prefix(k) for k in red.get("team_keys", [])) if t]
        blue_teams = [t for t in (strip_team_prefix(k) for k in blue.get("team_keys", [])) if t]

        alliances = None
        if len(red_teams) == 3 and len(blue_teams) == 3:
            alliances = {"red": red_teams, "blue": blue_teams}

        score = None
        red_score, blue_score = red.get("score"), blue.get("score")
        # TBA uses -1 for "not played yet".
        if isinstance(red_score, int) and isinstance(blue_score, int):
            if red_score >= 0 and blue_score >= 0:
                score = {"red": red_score, "blue": blue_score}

        return alliances, score

    def find_match_for_video(self, video_id: str, event_key: str) -> str | None:
        """Resolve a match key from a YouTube id, using TBA's per-match `videos` array.

        Doc 2's most reliable alignment source: "TBA `videos` field with an explicit match
        association." Only searches within one event, because that is the only scope where
        TBA exposes a full match list.
        """
        if not self.enabled or not video_id or not event_key:
            return None
        try:
            matches = self._fetch(f"/event/{event_key}/matches/simple") or []
        except Exception:
            return None
        for match in matches:
            for video in match.get("videos") or []:
                if video.get("type") != "youtube":
                    continue
                # Keys can carry a timestamp suffix: "dQw4w9WgXcQ?t=120".
                key = str(video.get("key", "")).split("?", 1)[0]
                if key == video_id:
                    return match.get("key")
        return None
