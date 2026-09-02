"""Turn a model's own predictions into training data for its successor.

This is self-training, and it works: a detector's confident predictions on easy examples are
mostly right, and there is far more unlabelled footage than anyone will ever hand-label.

It also has one specific way of going wrong, and it goes wrong quietly. The model's MISTAKES
become labels too. Train on them and v2 does not merely inherit v1's errors, it learns them as
ground truth and makes them more confidently. A blind spot -- robots at the far end of the field,
say -- becomes "there is no robot there", which teaches v2 to miss them harder than v1 did. The
loop has no natural correction in it, because the thing being asked and the thing answering are
the same model.

So everything here is a brake:

  * a confidence floor far above the operating threshold, because the point is to harvest the
    easy cases, not the interesting ones;
  * agreement between independent detectors where available, which is the only evidence in the
    pipeline that does not come from the model being retrained;
  * a physical sanity cap, since a frame claiming more robots than a field holds is wrong
    regardless of how confident anything is;
  * a hard ratio limit, so pseudo-labels cannot outvote the human-labelled data they are
    supposed to be supplementing; and
  * `pseudo: true` on every row, so no future reader mistakes these for labels a person drew.

None of that makes the output ground truth. It makes it a supplement whose failure mode is
bounded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: Well above the 0.35 used for labelling. Self-training should take the cases the model finds
#: obvious; the marginal ones are exactly where its errors live.
MIN_CONFIDENCE = 0.60

#: Detectors that must independently back a box. 1 is permitted and unsafe -- with a single model
#: there is no evidence in the loop that did not come from the model being retrained.
MIN_AGREEMENT = 2

#: Six robots per field, plus slack for an adjacent field in shot. A frame above this is wrong
#: about something, so nothing from it can be trusted.
MAX_BOXES_PER_FRAME = 8

#: Pseudo-labels may not exceed this fraction of the human-labelled set they supplement. Past
#: roughly half, the model is mostly learning from itself.
MAX_PSEUDO_RATIO = 0.5


@dataclass
class PseudoStats:
    frames_seen: int = 0
    frames_kept: int = 0
    frames_over_cap: int = 0
    boxes_seen: int = 0
    boxes_kept: int = 0
    rejected_low_confidence: int = 0
    rejected_low_agreement: int = 0
    dropped_by_ratio: int = 0
    single_detector: bool = False
    per_collection: dict = field(default_factory=dict)


def select_frames(
    collections: list[Path],
    min_confidence: float = MIN_CONFIDENCE,
    min_agreement: int = MIN_AGREEMENT,
    max_boxes: int = MAX_BOXES_PER_FRAME,
    stats: PseudoStats | None = None,
    consensus_name: str = "detector-consensus.jsonl",
) -> list[tuple[Path, dict, list[dict]]]:
    """Pick (collection, frame_row, boxes) triples worth promoting to training data."""
    stats = stats or PseudoStats()
    chosen: list[tuple[Path, dict, list[dict]]] = []

    for collection in collections:
        consensus = collection / consensus_name
        if not consensus.exists():
            continue
        frames = {
            json.loads(line)["frame_id"]: json.loads(line)
            for line in (collection / "frames.jsonl").read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        }
        kept_here = 0
        for line in consensus.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            stats.frames_seen += 1
            if len(row.get("detectors", [])) < 2:
                stats.single_detector = True

            boxes = row.get("boxes", [])
            stats.boxes_seen += len(boxes)

            keep = []
            for box in boxes:
                if box.get("confidence", 0.0) < min_confidence:
                    stats.rejected_low_confidence += 1
                    continue
                if box.get("agreement_count", 1) < min_agreement:
                    stats.rejected_low_agreement += 1
                    continue
                keep.append(box)

            if not keep:
                continue
            if len(keep) > max_boxes:
                # More robots than exist. Not a frame to learn from at any confidence.
                stats.frames_over_cap += 1
                continue

            frame = frames.get(row["frame_id"])
            if frame is None:
                continue
            chosen.append((collection, frame, keep))
            stats.frames_kept += 1
            stats.boxes_kept += len(keep)
            kept_here += 1
        if kept_here:
            stats.per_collection[collection.name] = kept_here

    return chosen


def enforce_ratio(
    chosen: list, human_image_count: int, max_ratio: float = MAX_PSEUDO_RATIO,
    stats: PseudoStats | None = None,
) -> list:
    """Cap pseudo-labels so they supplement human labels rather than outvote them.

    Trimmed from the end of a deterministically ordered list, so the same inputs always yield the
    same dataset.
    """
    limit = int(human_image_count * max_ratio)
    if len(chosen) <= limit:
        return chosen
    if stats is not None:
        stats.dropped_by_ratio = len(chosen) - limit
    return chosen[:limit]


def write_yolo(
    chosen: list[tuple[Path, dict, list[dict]]],
    out_dir: Path,
    split: str = "train",
) -> int:
    """Write the selection as YOLO labels, marked as machine-generated.

    Everything lands in `train` on purpose. A pseudo-label must never enter a validation or test
    split: measuring a model against its own predecessor's output tells you the two agree, which
    is not the question anyone is asking.
    """
    import shutil

    images_dir = out_dir / split / "images"
    labels_dir = out_dir / split / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    manifest = []
    for collection, frame, boxes in chosen:
        source = collection / frame["image_path"]
        if not source.exists():
            continue
        name = f"ps_{frame['frame_id']}.jpg"
        shutil.copy2(source, images_dir / name)

        lines = []
        for box in boxes:
            cx = box["x"] + box["w"] / 2
            cy = box["y"] + box["h"] / 2
            lines.append(f"0 {cx:.6f} {cy:.6f} {box['w']:.6f} {box['h']:.6f}")
        (labels_dir / f"ps_{frame['frame_id']}.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

        manifest.append({
            "file": name,
            "frame_id": frame["frame_id"],
            "match_id": frame.get("match_id"),
            "boxes": len(boxes),
            "pseudo": True,
        })
        written += 1

    (out_dir / "pseudo-manifest.json").write_text(
        json.dumps({"pseudo": True, "count": written, "frames": manifest}, indent=2),
        encoding="utf-8")
    return written
