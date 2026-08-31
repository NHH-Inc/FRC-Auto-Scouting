"""Drop labels that are impossible, without a human looking at anything.

This is NOT a substitute for review, and it cannot be. Review catches boxes that are *wrong* --
on the wrong object, or loose, or missing. Nothing here can see that. All this does is discard
labels that violate facts about FRC that hold regardless of what any frame contains:

  * An FRC field has six robots. A frame proposing nine of them is wrong about at least three,
    and there is no way to know which three, so the frame is not usable as ground truth.
  * A single robot never fills a quarter of a broadcast frame outside a replay close-up, and
    close-ups are excluded from training anyway.

Everything that survives is still an unverified guess. The point is only that a demo model should
not be taught arithmetic that contradicts the sport.

Frames are dropped whole rather than trimmed: with nine boxes and six robots, deleting three at
random is not a correction, it is a coin flip that leaves the same lie in the data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Six robots per FRC match. The slack allows for a genuinely visible robot from an adjacent
#: field at a multi-field event, plus one honest duplicate; beyond that the frame is guessing.
MAX_ROBOTS_PER_FRAME = 8

#: A single robot occupying more than this share of frame is not a robot -- it is the field, a
#: replay close-up, or the model boxing the whole image.
MAX_BOX_AREA = 0.25

#: Below this a box carries no trainable detail at 640px, the resolution RF-DETR trains at.
MIN_BOX_AREA = 0.0015

#: Robots are roughly as tall as they are wide. Anything much wider is a banner, a bumper wall,
#: or the score bug.
MAX_ASPECT = 3.0


def box_is_plausible(box: dict[str, Any]) -> bool:
    area = box["w"] * box["h"]
    if not (MIN_BOX_AREA <= area <= MAX_BOX_AREA):
        return False
    if box["h"] <= 0:
        return False
    aspect = box["w"] / box["h"]
    return (1.0 / MAX_ASPECT) <= aspect <= MAX_ASPECT


def filter_consensus(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return (kept rows, counts). A dropped frame keeps its image but loses its boxes."""
    stats = {"frames": len(rows), "frames_dropped": 0, "boxes_in": 0,
             "boxes_dropped_geometry": 0, "boxes_out": 0}
    kept: list[dict[str, Any]] = []

    for row in rows:
        boxes = row.get("boxes", [])
        stats["boxes_in"] += len(boxes)

        plausible = [b for b in boxes if box_is_plausible(b)]
        stats["boxes_dropped_geometry"] += len(boxes) - len(plausible)

        if len(plausible) > MAX_ROBOTS_PER_FRAME:
            # More robots than the sport allows. Which ones are wrong is unknowable from here,
            # so the whole frame stops claiming to be labelled.
            stats["frames_dropped"] += 1
            plausible = []

        stats["boxes_out"] += len(plausible)
        kept.append({**row, "boxes": plausible, "sanity_filtered": True})

    return kept, stats


def filter_collection(collection: Path, labels_file: str = "model-consensus.jsonl",
                      output_name: str = "model-consensus-filtered.jsonl") -> dict[str, int]:
    """Write a filtered copy alongside the original. The original is never modified."""
    source = collection / labels_file
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    kept, stats = filter_consensus(rows)

    target = collection / output_name
    target.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in kept), encoding="utf-8"
    )
    return stats
