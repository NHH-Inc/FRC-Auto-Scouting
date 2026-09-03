"""Turn the dense labelling pass into a training dataset.

The dense pass samples at 5 Hz because temporal linking needs adjacent detections to overlap.
Training does not want that rate. Consecutive 5 Hz frames are near-identical, so exporting all
54,000 of them would hand the trainer roughly fifteen copies of every moment rather than fifteen
different moments -- inflating the dataset while adding almost no information, and biasing it
toward whatever happens to last a long time on screen.

So the two rates do different jobs, and that is deliberate: sample densely to EARN the temporal
corroboration, then subsample widely to SPEND it on diverse training data.

Three rules that keep this from poisoning the next model:

  * Only corroborated boxes. A detection backed by both the detector and temporal persistence is
    the whole point; an uncorroborated one is exactly the guess we should not be teaching from.
  * Pseudo-labels go to TRAIN only, never valid or test. Validating against the model's own output
    measures agreement with itself, which always looks excellent and means nothing. The human
    splits stay the only yardstick.
  * The pseudo count is capped against the human count, so machine labels supplement human ones
    rather than outvoting them. Error amplification is the failure mode of self-training, and a
    ratio cap is the standard brake.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .pseudo_label import (
    MAX_BOXES_PER_FRAME, MAX_PSEUDO_RATIO, MIN_AGREEMENT, MIN_CONFIDENCE)

#: Seconds between exported frames from one match. At 5 Hz the pass produces a frame every 0.2s;
#: four seconds apart is far enough that the robots have moved and the scene genuinely differs.
MIN_GAP_SECONDS = 4.0

#: A frame with no surviving box teaches "there is nothing here". Some of that is healthy -- it is
#: how a detector learns not to hallucinate on empty carpet -- but a dataset dominated by empties
#: teaches it to predict nothing at all.
MAX_EMPTY_SHARE = 0.10

#: Anything scoring above this is a plausible robot, even if we would not assert it as a label.
#: The gap between this and MIN_CONFIDENCE is the doubt band, and a frame with anything in that
#: band is not safe to teach from.
DOUBT_FLOOR = 0.25


@dataclass
class Selection:
    match_id: str
    video_path: str
    t_seconds: float
    boxes: list


@dataclass
class ExportStats:
    rows_read: int = 0
    frames_selected: int = 0
    frames_written: int = 0
    boxes_written: int = 0
    empties: int = 0
    dropped_uncorroborated: int = 0
    dropped_low_confidence: int = 0
    dropped_incomplete: int = 0
    per_match: dict = field(default_factory=dict)


def keep_box(box: dict) -> tuple[bool, str]:
    """Whether one fused box is trustworthy enough to teach from."""
    if box.get("agreement_count", 0) < MIN_AGREEMENT:
        return False, "uncorroborated"
    if box.get("confidence", 0.0) < MIN_CONFIDENCE:
        return False, "low_confidence"
    return True, ""


def labels_look_complete(boxes: list[dict]) -> bool:
    """Whether a frame's accepted labels plausibly cover every robot actually in it.

    This is the rule that keeps self-training from going backwards, and it was added after
    measuring: 77% of otherwise-acceptable frames carried only one to three boxes when six robots
    are on the field. An object detector treats every unlabelled region as background, so a frame
    where four robots went unlabelled does not merely fail to teach -- it actively teaches that
    robots are not robots. That is how a pseudo-labelled second generation comes out worse than the
    first while its metrics still look reasonable.

    Counting boxes cannot separate the two cases on its own, because a close-up shot legitimately
    contains two robots. What distinguishes them is DOUBT: if lowering the bar to DOUBT_FLOOR
    reveals candidates we were unwilling to label, there are probably robots here we are about to
    call background. If nothing appears between the two thresholds, whatever is in this frame we
    have caught, and the frame is safe.
    """
    if any(b.get("confidence", 0.0) >= DOUBT_FLOOR
           and b.get("agreement_count", 0) < MIN_AGREEMENT
           for b in boxes):
        return False        # an uncorroborated candidate is still a candidate
    return not any(DOUBT_FLOOR <= b.get("confidence", 0.0) < MIN_CONFIDENCE for b in boxes)


def select(
    label_dir: Path | str,
    manifest_path: Path | str,
    min_gap: float = MIN_GAP_SECONDS,
    stats: ExportStats | None = None,
) -> list[Selection]:
    """Choose which dense-labelled frames are worth extracting, spaced out over each match."""
    stats = stats or ExportStats()
    videos = {
        e["match_id"]: e["path"]
        for e in json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    }

    chosen: list[Selection] = []
    for path in sorted(Path(label_dir).glob("*-dense.jsonl")):
        match_id = path.name.replace("-dense.jsonl", "")
        if match_id not in videos:
            continue
        last_t = -1e9
        taken = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            stats.rows_read += 1
            t = row["t_seconds"]
            if t - last_t < min_gap:
                continue

            if not labels_look_complete(row["boxes"]):
                stats.dropped_incomplete += 1
                continue

            kept = []
            for box in row["boxes"]:
                ok, why = keep_box(box)
                if ok:
                    kept.append(box)
                elif why == "uncorroborated":
                    stats.dropped_uncorroborated += 1
                else:
                    stats.dropped_low_confidence += 1

            if len(kept) > MAX_BOXES_PER_FRAME:
                # More boxes than the field can hold means the detector is confused here, not that
                # the frame is unusually rich. Teaching from it propagates the confusion.
                continue

            last_t = t
            taken += 1
            chosen.append(Selection(match_id, videos[match_id], t, kept))
        stats.per_match[match_id] = taken

    # Trim the empties down to a healthy minority rather than dropping them entirely.
    with_boxes = [s for s in chosen if s.boxes]
    empties = [s for s in chosen if not s.boxes]
    allowed = int(len(with_boxes) * MAX_EMPTY_SHARE / max(1e-9, 1 - MAX_EMPTY_SHARE))
    step = max(1, len(empties) // max(1, allowed)) if allowed else 0
    kept_empties = empties[::step][:allowed] if allowed else []

    out = sorted(with_boxes + kept_empties, key=lambda s: (s.match_id, s.t_seconds))
    stats.frames_selected = len(out)
    stats.empties = len(kept_empties)
    return out


def cap_against_human(selections: list[Selection], human_train_count: int,
                      ratio: float = MAX_PSEUDO_RATIO) -> list[Selection]:
    """Keep machine labels a minority partner to the human ones.

    Evenly spaced rather than truncated, so trimming does not silently drop whole matches from the
    end of the alphabet.
    """
    limit = int(human_train_count * ratio / max(1e-9, 1 - ratio))
    if len(selections) <= limit:
        return selections
    step = len(selections) / limit
    return [selections[int(i * step)] for i in range(limit)]


def extract_and_write(
    selections: list[Selection],
    out_root: Path | str,
    stats: ExportStats | None = None,
    jpeg_quality: int = 90,
) -> Path:
    """Pull the chosen frames out of their videos and write YOLO images + labels.

    Videos are read straight through rather than seeked. Seeking a long H.264 file to an arbitrary
    timestamp lands on the nearest keyframe, which is not the frame the labels describe -- the
    boxes would be attached to a slightly different image, and nothing would announce it.
    """
    import cv2

    stats = stats or ExportStats()
    root = Path(out_root)
    (root / "train" / "images").mkdir(parents=True, exist_ok=True)
    (root / "train" / "labels").mkdir(parents=True, exist_ok=True)

    by_match: dict[str, list[Selection]] = {}
    for s in selections:
        by_match.setdefault(s.match_id, []).append(s)

    for match_id, wanted in sorted(by_match.items()):
        cap = cv2.VideoCapture(wanted[0].video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        targets = {round(s.t_seconds * fps): s for s in wanted}
        index = 0
        while targets:
            ok, image = cap.read()
            if not ok:
                break
            sel = targets.pop(index, None)
            if sel is not None:
                stem = "{}_{:08d}".format(match_id, int(sel.t_seconds * 1000))
                cv2.imwrite(str(root / "train" / "images" / (stem + ".jpg")), image,
                            [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                lines = []
                for b in sel.boxes:
                    cx = b["x"] + b["w"] / 2.0
                    cy = b["y"] + b["h"] / 2.0
                    lines.append("0 {:.6f} {:.6f} {:.6f} {:.6f}".format(cx, cy, b["w"], b["h"]))
                (root / "train" / "labels" / (stem + ".txt")).write_text(
                    "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                stats.frames_written += 1
                stats.boxes_written += len(sel.boxes)
            index += 1
        cap.release()

    (root / "PROVENANCE.md").write_text(
        "# Machine-generated labels\n\n"
        "{} frames, {} boxes, produced by the dense labelling pass: YOLO detections\n"
        "corroborated by temporal persistence.\n\n"
        "These are PROPOSALS, not ground truth. Every box here survived two filters -- the\n"
        "detector's own confidence (>= {}) and agreement between the detector and temporal\n"
        "persistence (>= {} sources) -- but no human has looked at them.\n\n"
        "They belong in TRAIN only. Validating against them measures the model's agreement with\n"
        "itself, which always looks excellent and means nothing.\n".format(
            stats.frames_written, stats.boxes_written, MIN_CONFIDENCE, MIN_AGREEMENT),
        encoding="utf-8")
    return root
