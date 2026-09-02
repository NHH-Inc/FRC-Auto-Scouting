"""Carry a track through a short occlusion by projecting its last known motion.

A robot that disappears behind a game piece has not stopped existing. The camera did not move,
physics still applies, and its position a fifth of a second later is strongly constrained. Filling
that hole keeps one robot as one track instead of fragmenting it into two.

The rule that makes this safe is already in the contract, in the two gap reasons:

    detection_lost   we stopped seeing it, camera unchanged  -> estimating is reasonable
    shot_change      the camera cut away                     -> estimating is fabrication

Across a `shot_change` the robot could be anywhere: the broadcast may return three seconds later
from a different angle with the field rearranged. Doc 0 forbids interpolating across a gap for
exactly this reason, and nothing here overrides that. This module only fills `detection_lost`.

Four further brakes, because a plausible invented position is worse than an honest hole:

  * a horizon, past which the estimate stops rather than drifting indefinitely;
  * confidence that decays with time, so a stale estimate is visibly weaker than a fresh one;
  * velocity taken from several real observations rather than the last pair, since a single
    jittery box otherwise sets the direction for the whole occlusion; and
  * `estimated: true` on every synthesised sample, so no consumer can mistake a guess for an
    observation. That is the same principle as corrections never overwriting raw model output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Longest occlusion worth estimating through. Beyond a second the constant-velocity assumption
#: has usually stopped being true -- robots turn, collide and get defended.
MAX_COAST_SECONDS = 1.0

#: Confidence multiplier applied per second of coasting, so an estimate half a second old is
#: visibly weaker than one a tenth of a second old.
CONFIDENCE_DECAY_PER_SECOND = 0.6

#: Observations used to estimate velocity. Five, not three: the estimator below is robust only
#: when clean pairs outnumber contaminated ones, and with three samples a single bad box is in
#: the majority of pairs.
VELOCITY_WINDOW = 5


@dataclass(frozen=True)
class Sample:
    """One observation of a track: a normalised box at a time."""
    t: float
    x: float
    y: float
    w: float
    h: float
    confidence: float = 1.0
    estimated: bool = False


def estimate_velocity(samples: list[Sample], window: int = VELOCITY_WINDOW) -> tuple[float, float]:
    """Velocity in normalised units per second, from the last few real observations.

    Uses a Theil-Sen estimator -- the median of the slopes between every pair of observations --
    rather than least squares. Least squares was tried first and is the wrong tool here: it
    minimises squared error, so one badly-placed box pulls the fit hard toward itself, and a
    single jittery detection then sets the direction the track is carried in for the whole
    occlusion. Taking a median instead means a bad sample has to outnumber the good ones to
    matter, which over five observations it does not.

    Only real observations count. Feeding estimated samples back in would let a coast compound on
    its own output and drift.
    """
    real = [s for s in samples if not s.estimated][-window:]
    if len(real) < 2:
        return (0.0, 0.0)

    def slope(values: list[float]) -> float:
        slopes = []
        for i in range(len(real)):
            for j in range(i + 1, len(real)):
                dt = real[j].t - real[i].t
                if abs(dt) > 1e-12:
                    slopes.append((values[j] - values[i]) / dt)
        if not slopes:
            return 0.0
        slopes.sort()
        mid = len(slopes) // 2
        return slopes[mid] if len(slopes) % 2 else (slopes[mid - 1] + slopes[mid]) / 2.0

    return (slope([s.x for s in real]), slope([s.y for s in real]))


def coast(
    samples: list[Sample],
    until: float,
    step: float,
    gap_reason: str,
    max_coast: float = MAX_COAST_SECONDS,
) -> list[Sample]:
    """Synthesise samples across a gap, or return nothing if estimating is not allowed.

    `gap_reason` is the contract's reason string. Anything other than `detection_lost` yields an
    empty list -- notably `shot_change`, where the camera moved and the robot's position is
    genuinely unknown.
    """
    if gap_reason != "detection_lost":
        return []
    if not samples or step <= 0:
        return []

    last = samples[-1]
    vx, vy = estimate_velocity(samples)

    out: list[Sample] = []
    t = last.t + step
    while t <= until + 1e-9:
        elapsed = t - last.t
        if elapsed > max_coast:
            break
        # Constant velocity. Accelerations over a fraction of a second are small next to the
        # uncertainty already present in the box itself.
        x = last.x + vx * elapsed
        y = last.y + vy * elapsed
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            # Coasted off the frame. Whatever happened, it is no longer something we can claim
            # to have observed a position for.
            break
        out.append(Sample(
            t=t, x=x, y=y, w=last.w, h=last.h,
            confidence=last.confidence * (CONFIDENCE_DECAY_PER_SECOND ** elapsed),
            estimated=True,
        ))
        t += step
    return out


def fill_gap(
    before: list[Sample],
    after: list[Sample],
    step: float,
    gap_reason: str,
    max_coast: float = MAX_COAST_SECONDS,
) -> list[Sample]:
    """Fill between two observed runs of the same track.

    When the gap is short enough to bridge entirely, the estimate is additionally pulled toward
    the observation that follows it -- a hole with a known end is an interpolation problem, and
    ignoring the far side would leave a visible jump where the real detections resume.
    """
    if gap_reason != "detection_lost" or not before or not after:
        return []

    start, end = before[-1], after[0]
    span = end.t - start.t
    if span <= 0 or span > max_coast:
        return coast(before, end.t - step, step, gap_reason, max_coast)

    out: list[Sample] = []
    t = start.t + step
    while t < end.t - 1e-9:
        fraction = (t - start.t) / span
        elapsed = t - start.t
        out.append(Sample(
            t=t,
            x=start.x + (end.x - start.x) * fraction,
            y=start.y + (end.y - start.y) * fraction,
            w=start.w + (end.w - start.w) * fraction,
            h=start.h + (end.h - start.h) * fraction,
            confidence=min(start.confidence, end.confidence)
            * (CONFIDENCE_DECAY_PER_SECOND ** elapsed),
            estimated=True,
        ))
        t += step
    return out
