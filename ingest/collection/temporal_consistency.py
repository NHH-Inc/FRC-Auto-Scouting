"""Corroborate detections against time instead of against a second model.

We have video, and physics is an independent witness a single detector cannot be. A robot seen in
one frame and gone the next is almost certainly a hallucination; a box that persists across a run
of frames at a consistent position is real, because objects do not blink in and out of existence.
That persistence is genuine evidence, it costs no second model and no second training run, and it
is more trustworthy right now than a weak second detector whose boxes never even overlap the
first's.

This is the second opinion the confidence system was missing. A detector's own confidence says how
sure it was looking at one frame; temporal persistence says whether the world agreed with it over
several. A box confirmed by both is trustworthy in a way neither signal is alone.

It requires DENSE sampling. The review collections are 0.25 fps -- one frame every four seconds --
across which a robot travels most of the field, so consecutive boxes do not overlap and linking is
meaningless. This runs on its own dense pass of the source video, several frames per second, where
adjacent detections of one robot really do sit almost on top of each other.

The honest limit, stated because persistence is corroboration and not proof: a stationary false
positive persists too. A robot-shaped graphic on the field wall, detected every frame, earns a
high persistence score while being wrong. Temporal consistency raises confidence in things that
are stable; it cannot tell a stable truth from a stable error. It is one more brake, not a
guarantee -- the same footing as every other signal in this pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .box_fusion import iou

#: Boxes in adjacent frames overlapping by at least this are treated as the same object. Lower
#: than the fusion threshold, because a moving robot's box shifts between frames even at several
#: Hz, and demanding tight overlap would sever a real track at every step.
LINK_IOU = 0.30

#: A track this many frames long or more is considered corroborated. Two frames can be a
#: coincidence -- one flicker landing near another -- three is a pattern.
MIN_PERSISTENT_FRAMES = 3

#: Frames a track may miss before it is closed. A brief occlusion or a dropped detection should
#: not end a track that plainly resumes; this is the temporal analogue of the tracker's gap
#: tolerance.
MAX_MISSED_FRAMES = 2


@dataclass
class Track:
    """One object followed across frames. `members` are (frame_index, box) pairs."""
    members: list = field(default_factory=list)
    missed: int = 0

    @property
    def last_box(self) -> dict:
        return self.members[-1][1]

    @property
    def frame_span(self) -> int:
        """Frames from first to last appearance, counting the gaps a real track survives.

        Length, not member count, is what persistence should measure: a track seen at frames
        0,1,_,3 persisted for four frames despite missing one, and rewarding only the three hits
        would penalise it for the occlusion it survived.
        """
        if not self.members:
            return 0
        return self.members[-1][0] - self.members[0][0] + 1

    @property
    def persistent(self) -> bool:
        return self.frame_span >= MIN_PERSISTENT_FRAMES


def link_tracks(
    frames: list[list[dict]],
    link_iou: float = LINK_IOU,
    max_missed: int = MAX_MISSED_FRAMES,
) -> list[Track]:
    """Link per-frame detections into tracks by greedy IoU across adjacent frames.

    `frames` is time-ordered; each entry is that frame's boxes. The same greedy nearest-overlap
    rule the C++ tracker uses, kept deliberately simple: one detector's dense output does not need
    a Kalman filter to answer "is this the same robot as last frame".
    """
    active: list[Track] = []
    finished: list[Track] = []

    for index, boxes in enumerate(frames):
        # Match each detection to the best unclaimed active track it overlaps.
        claimed: set[int] = set()
        for box in boxes:
            best_track = None
            best_iou = link_iou
            for track in active:
                if id(track) in claimed:
                    continue
                score = iou(track.last_box, box)
                if score >= best_iou:
                    best_track, best_iou = track, score
            if best_track is not None:
                best_track.members.append((index, box))
                best_track.missed = 0
                claimed.add(id(best_track))
            else:
                new = Track(members=[(index, box)])
                active.append(new)
                claimed.add(id(new))

        # Age tracks that went unmatched this frame; retire the ones past the miss tolerance.
        survivors = []
        for track in active:
            if id(track) in claimed:
                survivors.append(track)
                continue
            track.missed += 1
            if track.missed > max_missed:
                finished.append(track)
            else:
                survivors.append(track)
        active = survivors

    return finished + active


def annotate(
    frames: list[list[dict]],
    link_iou: float = LINK_IOU,
    max_missed: int = MAX_MISSED_FRAMES,
) -> list[list[dict]]:
    """Return the frames with each box carrying a temporal_persistence and adjusted confidence.

    Confidence is reweighted, not replaced. A detection's own score is kept as raw_confidence, and
    a persistence factor scales it: a box in a long stable track is boosted toward 1.0, a lone
    flicker is cut hard. The raw value survives so the adjustment is auditable and reversible --
    the same principle as corrections never overwriting model output.
    """
    tracks = link_tracks(frames, link_iou, max_missed)

    # Map each (frame, box identity) to the track carrying it, so the boost can be written back.
    factor_for: dict[tuple[int, int], float] = {}
    for track in tracks:
        span = track.frame_span
        # Saturating: one frame earns nothing, MIN_PERSISTENT_FRAMES earns full trust, and more
        # does not keep inflating -- a robot standing still for 200 frames is not 60x more real
        # than one confirmed over three.
        factor = min(1.0, span / MIN_PERSISTENT_FRAMES)
        for frame_index, box in track.members:
            factor_for[(frame_index, id(box))] = factor

    out: list[list[dict]] = []
    for index, boxes in enumerate(frames):
        annotated = []
        for box in boxes:
            factor = factor_for.get((index, id(box)), 0.0)
            raw = box.get("confidence", 0.0)
            annotated.append({
                **box,
                "raw_confidence": raw,
                "temporal_persistence": round(factor, 4),
                "confidence": round(raw * factor, 6),
                "temporally_confirmed": factor >= 1.0,
            })
        out.append(annotated)
    return out


def confirmed_boxes(frames: list[list[dict]], **kwargs) -> list[list[dict]]:
    """Per frame, only the detections a persistent track backs.

    This is the form box_fusion consumes as a source: feeding raw detections and their
    temporally-confirmed subset as two sources means a box present in both carries agreement from
    the world, not just from a second network.
    """
    return [
        [b for b in boxes if b["temporally_confirmed"]]
        for boxes in annotate(frames, **kwargs)
    ]
