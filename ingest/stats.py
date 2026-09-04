"""Aggregates and score reconstruction, SCHEMA_VERSION 3.

Doc 0: "Aggregates are never stored, only queried. If a stat is needed often enough to hurt,
add a materialized view, not a column." Everything here is computed on demand from event rows.

Cycle time is doc 0's vocabulary definition: the interval between one `reload` and the next
`reload` for the same TEAM. Acquire to acquire, so a missed shot still costs a cycle. Per team
rather than per track, because track ids are job-local and a re-identified robot may span
several. An unterminated final cycle is discarded, not counted.
"""

import json
import statistics
from functools import lru_cache
from pathlib import Path

SEASONS_DIR = Path(__file__).resolve().parent.parent / "contracts" / "seasons"


@lru_cache(maxsize=8)
def season_config(year: int) -> dict | None:
    """Doc 0: selected by the job's `season`, so old footage stays analyzable.

    Returns None for an unknown season rather than falling back to a current one -- doc 0:
    "Anything unrecognized is a bug, not a fallback."
    """
    path = SEASONS_DIR / f"{year}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def points_for(phase: str, goal: str | None, cfg: dict | None) -> int:
    """Points for one made shot in a phase, at a given goal.

    v3 added `goal`, so this no longer assumes every shot went in the high goal. A null goal
    means the model could not place the shot: it scores 0 rather than guessing, which keeps
    the accuracy comparison honest about what the pipeline actually knows.

    Every value is a zero placeholder until the game is public; doc 0: "Do not invent values
    to make a test pass."
    """
    if not cfg or not goal:
        return 0
    group = cfg.get("point_values", {}).get(phase) or {}
    return int(group.get(f"shot_made_{goal}", 0))


def scoring_is_meaningful(cfg: dict | None) -> bool:
    """False while every point value is still a zero placeholder."""
    if not cfg:
        return False
    groups = cfg.get("point_values", {}).values()
    return any(v for group in groups for v in (group or {}).values())


def legal_goals(cfg: dict | None) -> set[str] | None:
    """Legal `goal` values for a season, or None when the season is unknown."""
    if not cfg:
        return None
    return set(cfg.get("goals") or [])


def _alliance_of(team, alliances) -> str | None:
    if team is None or not alliances:
        return None
    if team in (alliances.get("red") or []):
        return "red"
    if team in (alliances.get("blue") or []):
        return "blue"
    return None


def reconstruct_score(events: list[dict], alliances: dict | None, cfg: dict | None) -> dict:
    """Sum made shots into an alliance score.

    An event with team=None contributes nothing: an unidentified robot cannot be credited to
    an alliance, and guessing would quietly inflate the number this exists to test.
    """
    score = {"red": 0, "blue": 0}
    if not alliances:
        return score
    for event in events:
        side = _alliance_of(event.get("team"), alliances)
        if side is None:
            continue
        if event.get("event_type") == "shot_made":
            score[side] += points_for(
                event.get("phase", "unknown"), event.get("goal"), cfg
            )
    return score


def _paired_seconds(events, start_type: str, end_type: str, match_end: float) -> float:
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


def team_stats(
    team: int,
    events: list[dict],
    cfg: dict | None,
    event_key: str | None,
    matches_played: int,
    min_confidence: float = 0.0,
    low_confidence_threshold: float = 0.5,
) -> dict:
    """Contract E's team_stats shape. Fields may be added additively; none renamed."""
    if cfg:
        match_end = float(cfg["auto_seconds"]) + float(cfg["teleop_seconds"])
    else:
        match_end = float("inf")

    mine = [e for e in events if e.get("team") == team]

    reload_times = sorted(
        (e.get("t_seconds") or 0.0) for e in mine if e.get("event_type") == "reload"
    )
    cycles = [reload_times[i] - reload_times[i - 1] for i in range(1, len(reload_times))]

    shot_times = sorted(
        (e.get("t_seconds") or 0.0) for e in mine if e.get("event_type") == "shot_attempt"
    )
    intervals = [shot_times[i] - shot_times[i - 1] for i in range(1, len(shot_times))]

    logged_attempts = sum(1 for e in mine if e.get("event_type") == "shot_attempt")
    made = sum(1 for e in mine if e.get("event_type") == "shot_made")
    # A robot cannot score more shots than it took. The two are separate events -- the golden
    # fixture has 80 attempts and 55 makes, none sharing a timestamp -- so a scout logging under
    # time pressure can easily record the makes and miss the attempts. Believing that literally
    # reports "1 made of 0 attempted, accuracy unknown", which reads as a broken tool rather than
    # as missing input. Taking the larger of the two is a floor on what was attempted, and it can
    # never push accuracy above 1.
    attempts = max(logged_attempts, made)

    return {
        "team": team,
        "event_key": event_key,
        "min_confidence": min_confidence,
        "matches_played": matches_played,
        "cycles": len(cycles),
        # Median, not mean: one immobile robot produces a single enormous interval.
        "avg_cycle_seconds": statistics.median(cycles) if cycles else None,
        "shot_attempts": attempts,
        "shots_made": made,
        "shot_accuracy": (made / attempts) if attempts else None,
        "avg_shot_interval_seconds": statistics.fmean(intervals) if intervals else None,
        "reloads": len(reload_times),
        "defense_seconds": _paired_seconds(mine, "defense_start", "defense_end", match_end),
        "immobile_seconds": _paired_seconds(mine, "immobile_start", "immobile_end", match_end),
        "fouls": sum(1 for e in mine if e.get("event_type") == "foul"),
        "low_confidence_events": sum(
            1 for e in mine if (e.get("confidence") or 0.0) < low_confidence_threshold
        ),
    }
