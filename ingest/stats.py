"""Aggregates and score reconstruction.

Doc 0: "Aggregates are never stored, only queried. If a stat is needed often enough to hurt,
add a materialized view, not a column." Everything here is computed on demand from event
rows; nothing is written back.

Cycle time is measured acquire-to-acquire, between consecutive `reload` events for a team.
Doc 1 defines it as reload-to-score instead; the two produce materially different numbers
and the disagreement is logged as contracts/OPEN_QUESTIONS.md #11. Reload-to-reload is used
here because a missed shot should still cost a cycle, and because it is measured per team
rather than per track -- track ids are job-local and a re-identified robot gets a new one.
"""

import json
import statistics
from functools import lru_cache
from pathlib import Path

SEASON_PATH = Path(__file__).resolve().parent.parent / "contracts" / "season_2026.json"


@lru_cache(maxsize=1)
def season_config() -> dict:
    with open(SEASON_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def points_for(phase: str) -> int:
    return int(season_config()["scoring"]["shot_made"].get(phase, 0))


def _alliance_of(team, alliances) -> str | None:
    if team is None or not alliances:
        return None
    if team in (alliances.get("red") or []):
        return "red"
    if team in (alliances.get("blue") or []):
        return "blue"
    return None


def reconstruct_score(events: list[dict], alliances: dict | None) -> dict:
    """Sum made shots and fouls into an alliance score.

    An event with team=None contributes nothing: an unidentified robot cannot be credited to
    an alliance, and guessing would quietly inflate the accuracy number this exists to test.
    """
    score = {"red": 0, "blue": 0}
    if not alliances:
        return score
    foul_points = int(season_config()["scoring"]["foul_points_to_opponent"])
    for event in events:
        side = _alliance_of(event.get("team"), alliances)
        if side is None:
            continue
        if event.get("event_type") == "shot_made":
            score[side] += points_for(event.get("phase", "unknown"))
        elif event.get("event_type") == "foul":
            score["blue" if side == "red" else "red"] += foul_points
    return score


def _paired_seconds(events: list[dict], start_type: str, end_type: str, match_end: float) -> float:
    """Total seconds spanned by start/end pairs; an unclosed interval runs to match_end."""
    total = 0.0
    opened_at = None
    for event in sorted(events, key=lambda e: e.get("t_seconds") or 0.0):
        if event.get("event_type") == start_type and opened_at is None:
            opened_at = event.get("t_seconds") or 0.0
        elif event.get("event_type") == end_type and opened_at is not None:
            total += max(0.0, (event.get("t_seconds") or 0.0) - opened_at)
            opened_at = None
    if opened_at is not None:
        total += max(0.0, match_end - opened_at)
    return total


def team_stats(team: int, events: list[dict], event_key: str | None, matches_played: int) -> dict:
    periods = season_config()["periods"]
    match_end = float(periods["auto_seconds"]) + float(periods["teleop_seconds"])

    mine = [e for e in events if e.get("team") == team]
    reload_times = sorted(
        (e.get("t_seconds") or 0.0) for e in mine if e.get("event_type") == "reload"
    )
    cycles = [
        reload_times[i] - reload_times[i - 1] for i in range(1, len(reload_times))
    ]

    attempts = sum(1 for e in mine if e.get("event_type") == "shot_attempt")
    made = sum(1 for e in mine if e.get("event_type") == "shot_made")
    points = sum(
        points_for(e.get("phase", "unknown")) for e in mine if e.get("event_type") == "shot_made"
    )

    return {
        "team": team,
        "event_key": event_key,
        "matches_played": matches_played,
        "shot_attempts": attempts,
        "shots_made": made,
        "accuracy": (made / attempts) if attempts else None,
        "reloads": len(reload_times),
        "cycle_count": len(cycles),
        # Median, not mean: one immobile robot produces a single enormous interval.
        "median_cycle_seconds": statistics.median(cycles) if cycles else None,
        "best_cycle_seconds": min(cycles) if cycles else None,
        "defense_seconds": _paired_seconds(mine, "defense_start", "defense_end", match_end),
        "immobile_seconds": _paired_seconds(mine, "immobile_start", "immobile_end", match_end),
        "fouls": sum(1 for e in mine if e.get("event_type") == "foul"),
        "points_contributed": points,
    }
