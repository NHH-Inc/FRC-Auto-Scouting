"""Turn tracks and the scoreboard into events, which is the gap between a pipeline and scouting data.

The analyzer emits `match_start` and `match_end` and nothing else, so a real match ran the whole
way to the spreadsheet and exported zero rows: a row needs a team-attributed *event*, and there
were none. This closes that, for the part that can be closed honestly.

Three sources, in descending order of how much they are actually known:

  * **The clock.** Phase boundaries are arithmetic on the season config. Nothing is inferred and
    nothing can be wrong that is not already wrong in the config.

  * **Track geometry.** A robot whose box stops moving has stopped moving. Whether it died,
    was pinned, or is holding position is not knowable from pixels, so the event says
    `immobile`, which is what was observed, and lets a human read the cause.

  * **The scoreboard.** Scoring does not have to be inferred from a ball in flight: the broadcast
    states the score every frame. A rise from 34 to 38 is a scoring event at a known second for a
    known alliance. Reading it back gives 98-33 on a frame that shows 98-33, and the red score is
    monotonic across 35 readings.

**Why this does not emit shots yet.** Points are not shots. Turning "+5 to red" into a number of
`shot_made` needs `point_values` from the season config, and every value in 2026.json is a zero
placeholder -- nobody has filled them in. Dividing by a made-up number would produce confident
shot counts that are wrong, which is worse than none. So scoring *moments* are surfaced for a
human to attribute, and the shot arithmetic switches itself on the day the config is real.

Even without it, the timeline is worth having: it turns "watch two and a half minutes and spot the
scores" into "check these twelve moments", which is the difference between a scout keeping up with
a match and not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

#: A robot is called immobile only after this long without moving. Shorter than this is lining up
#: a shot, waiting for a game piece, or being briefly blocked -- all normal play.
MIN_IMMOBILE_SECONDS = 4.0

#: How far a box centre may drift, in frame widths, and still count as stationary. Detector jitter
#: on a parked robot is a pixel or two; this is several times that.
IMMOBILE_RADIUS = 0.012

#: A score reading must be confirmed this many times before it is believed. A single frame's OCR
#: misread the blue score twice in 35 samples, and one bad reading would otherwise invent a
#: scoring event and then a negative one.
SCORE_CONFIRMATIONS = 2


def phase_for(t: float, auto_seconds: float, teleop_seconds: float,
              endgame_seconds: float) -> str:
    """Which phase a timestamp falls in.

    Endgame is the tail of teleop rather than a fourth period, which is how the game is actually
    played and how the season config lays the numbers out.
    """
    if t < auto_seconds:
        return "auto"
    teleop_end = auto_seconds + teleop_seconds
    if t < teleop_end - endgame_seconds:
        return "teleop"
    if t < teleop_end:
        return "endgame"
    return "unknown"


def phase_changes(duration: float, config: dict, start_offset: float = 0.0) -> list[dict]:
    """The phase boundaries, in clip time.

    `start_offset` is where the match begins within the clip. It matters more than it looks: a
    clip is not a match, and on the first real run the file ran 215 seconds around 150 of play, so
    timing from zero put every boundary 21 seconds early and filed events either side of one under
    the wrong period. `match_anchor` recovers the offset from the scoreboard clock.

    Beyond that this is arithmetic on the season config, so nothing here can be wrong that is not
    already wrong in the config.
    """
    auto = float(config.get("auto_seconds") or 0)
    teleop = float(config.get("teleop_seconds") or 0)
    endgame = float(config.get("endgame_seconds") or 0)
    if auto <= 0 or teleop <= 0:
        return []

    boundaries = [(auto, "teleop")]
    if endgame > 0:
        boundaries.append((auto + teleop - endgame, "endgame"))

    out = []
    for t, phase in boundaries:
        at = t + start_offset
        if 0 < at < duration:
            out.append({"t_seconds": round(at, 3), "phase": phase,
                        "event_type": "phase_change", "confidence": 1.0, "team": None,
                        "track_id": None, "goal": None})
    return out


#: How many timer readings must agree on the same zero-time before it is used. OCR confuses 1
#: with 7 at this size, so a handful of readings disagree by a few seconds on every match.
MIN_ANCHOR_AGREEMENT = 4


def match_anchor(readings: list[tuple[float, int | None]], tolerance: float = 1.0
                 ) -> tuple[float, int] | None:
    """(clip time at which the match clock hits zero, how many readings agreed), or None.

    A clip is not a match. This one runs 215 seconds around 150 of play, so timing phases from the
    start of the file puts auto, teleop and endgame in the wrong places -- the first attempt had
    every boundary 21 seconds early, and events either side of one were filed under the wrong
    period.

    The clock gives the offset for free: clip time plus time remaining is the same number at every
    moment of the match, and that number is when the clock reaches zero. Readings that disagree
    are misreads rather than evidence of drift, so the most common value wins and the count of
    agreeing readings comes back with it -- a caller that sees two agreeing readings should not
    trust the answer the way it trusts twelve.
    """
    sums = [t + remaining for t, remaining in readings if remaining is not None]
    if not sums:
        return None
    best, best_count = None, 0
    for candidate in sums:
        agree = sum(1 for s in sums if abs(s - candidate) <= tolerance)
        if agree > best_count:
            best, best_count = candidate, agree
    if best is None or best_count < MIN_ANCHOR_AGREEMENT:
        return None
    return float(best), best_count


def match_start_offset(anchor: float, config: dict) -> float:
    """Clip time at which the match began, from where its clock reaches zero."""
    length = float(config.get("auto_seconds") or 0) + float(config.get("teleop_seconds") or 0)
    return anchor - length


@dataclass
class Span:
    start: float
    end: float


def immobile_spans(boxes: list[dict], radius: float = IMMOBILE_RADIUS,
                   min_seconds: float = MIN_IMMOBILE_SECONDS) -> list[Span]:
    """Stretches where a track's box centre stayed inside `radius`.

    Greedy and forward-only: a span runs until the robot leaves the circle its start defined. That
    keeps a slow drift across the field from being read as one long stationary period, which an
    average-position test would do.
    """
    if len(boxes) < 2:
        return []
    centres = [(b["t"], b["x"] + b["w"] / 2.0, b["y"] + b["h"] / 2.0) for b in boxes]
    spans: list[Span] = []
    anchor = 0
    for i in range(1, len(centres) + 1):
        at_end = i == len(centres)
        if not at_end:
            dx = centres[i][1] - centres[anchor][1]
            dy = centres[i][2] - centres[anchor][2]
            if (dx * dx + dy * dy) ** 0.5 <= radius:
                continue
        last = i - 1
        length = centres[last][0] - centres[anchor][0]
        if last > anchor and length >= min_seconds:
            spans.append(Span(centres[anchor][0], centres[last][0]))
        anchor = i if not at_end else anchor
    return spans


def immobility_events(track: dict, config: dict, start_offset: float = 0.0) -> list[dict]:
    """immobile_start / immobile_end for one track.

    A track with no team still produces these; the events carry the track id, so attributing the
    track later moves them onto a team in one action.
    """
    auto = float(config.get("auto_seconds") or 0)
    teleop = float(config.get("teleop_seconds") or 0)
    endgame = float(config.get("endgame_seconds") or 0)

    out = []
    for span in immobile_spans(track.get("boxes") or []):
        for t, kind in ((span.start, "immobile_start"), (span.end, "immobile_end")):
            out.append({
                "t_seconds": round(t, 3),
                # Phase is asked in match time; the timestamp stays in clip time, which is what
                # the player seeks to and what every box is stamped with.
                "phase": phase_for(t - start_offset, auto, teleop, endgame),
                "event_type": kind,
                # Geometry, not a model: the box demonstrably did not move. The uncertainty is in
                # what it means, not in whether it happened.
                "confidence": 0.9,
                "team": track.get("team"),
                "track_id": track.get("track_id"),
                "goal": None,
            })
    return out


def stable_scores(readings: list[tuple[float, int | None]],
                  confirmations: int = SCORE_CONFIRMATIONS) -> list[tuple[float, int]]:
    """Clean a noisy score timeline using the one rule the game guarantees.

    An alliance score never falls during a match. A reading below the running maximum is a misread,
    not a correction, and dropping it costs nothing -- the true value will be read again. A rise is
    only believed once it has been seen `confirmations` times, so a single hallucinated digit
    cannot invent a scoring event and then an impossible negative one.
    """
    best = 0
    pending: int | None = None
    pending_count = 0
    pending_time = 0.0
    out: list[tuple[float, int]] = []
    for t, value in readings:
        if value is None or value < best:
            continue
        if value == best:
            pending, pending_count = None, 0
            continue
        if value != pending:
            pending, pending_count, pending_time = value, 1, t
        else:
            pending_count += 1
        if pending_count >= confirmations:
            best = pending
            out.append((pending_time, best))
            pending, pending_count = None, 0
    return out


def scoring_moments(timeline: list[tuple[float, int]], alliance: str) -> list[dict]:
    """Where an alliance's score went up, and by how much."""
    moments = []
    previous = 0
    for t, value in timeline:
        if value > previous:
            moments.append({"t_seconds": round(t, 3), "alliance": alliance,
                            "points": value - previous})
            previous = value
    return moments


def shots_from_points(points: int, phase: str, config: dict) -> int | None:
    """How many made shots a point increase represents, or None when that is not knowable.

    Returns None whenever the season's point values are missing or zero, which is the case for
    2026: every entry in the config is a placeholder. Dividing by a guessed value would turn one
    scoring moment into a confident and wrong number of shots, and every per-team accuracy figure
    downstream would inherit it. Doc 0 is explicit -- do not invent values.
    """
    values = (config.get("point_values") or {}).get(phase) or {}
    candidates = [v for v in values.values() if isinstance(v, (int, float)) and v > 0]
    if not candidates:
        return None
    unit = min(candidates)
    if points % unit != 0:
        return None       # not a whole number of shots at any known value
    return int(points // unit)


def to_events(rows: list[dict], job_id: str, match_id: str, schema_version: int = 3,
              source: str = "model") -> list[dict]:
    """Give partial rows the identity and provenance Contract B requires."""
    out = []
    for row in rows:
        event = {
            "schema_version": schema_version,
            "event_id": str(uuid.uuid4()),
            "job_id": job_id,
            "match_id": match_id,
            "source": source,
            "field_x": None,
            "field_y": None,
        }
        event.update(row)
        out.append(event)
    return out
