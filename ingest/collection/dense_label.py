"""Densely label a match from its video, using time as the corroborating second opinion.

The review collections sample at 0.25 fps because a human had to look at every frame. This pass
is for the machine, not a person, so it samples densely -- several frames a second -- which is
what temporal consistency needs to link one robot's detections across adjacent frames.

The pipeline per match:

    sample the video at ~TARGET_HZ
      -> reject graphic frames (FIRST logo, score cards) before the detector wastes time on them
      -> YOLO detects robots on the rest
      -> temporal consistency scores each detection by how long its track persists
      -> fuse raw detections with their temporally-confirmed subset

The fusion step is the one that matters. A detection backed by both the detector's own confidence
and by persisting across frames carries agreement from the world, not just from one network -- the
second opinion RF-DETR was too weak to provide. The output confidence is that fused number, and
every box keeps its raw detector score and its persistence factor so the result is auditable.

This is training input for the next model, not ground truth. Every row is marked accordingly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .box_fusion import estimate_source_weights, fuse_frame
from .frame_quality import measure_image
from .temporal_consistency import annotate

#: Dense enough that a robot's box overlaps itself between frames, sparse enough that a match is
#: thousands of frames rather than tens of thousands. Five per second is the same rate the tracker
#: samples at.
TARGET_HZ = 5.0


@dataclass
class DenseStats:
    frames_sampled: int = 0
    frames_graphic: int = 0
    raw_detections: int = 0
    confirmed_detections: int = 0
    fused_boxes: int = 0
    corroborated: int = 0
    per_match: dict = field(default_factory=dict)


def label_sequence(
    frames_bgr: list,
    timestamps: list[float],
    detector,
    stats: DenseStats | None = None,
) -> list[dict]:
    """Label an in-memory frame sequence. Separated from video I/O so it is testable with stubs.

    Returns one row per sampled frame: its timestamp and the fused boxes. A graphic frame yields a
    row with no boxes rather than being dropped, so the row index still tracks video time.
    """
    stats = stats or DenseStats()

    raw_per_frame: list[list[dict]] = []
    for image in frames_bgr:
        stats.frames_sampled += 1
        if not measure_image(image).keep:
            stats.frames_graphic += 1
            raw_per_frame.append([])
            continue
        boxes = detector.detect(image)
        stats.raw_detections += len(boxes)
        raw_per_frame.append(boxes)

    # Persistence over the whole sequence, then fuse raw against the confirmed subset.
    annotated = annotate(raw_per_frame)
    confirmed_per_frame = [
        [b for b in frame if b.get("temporally_confirmed")] for frame in annotated
    ]
    stats.confirmed_detections += sum(len(f) for f in confirmed_per_frame)

    per_frame_sources = [
        {"detector": raw, "time": confirmed}
        for raw, confirmed in zip(raw_per_frame, confirmed_per_frame)
    ]
    weights = estimate_source_weights(per_frame_sources)

    rows = []
    for t, sources in zip(timestamps, per_frame_sources):
        fused = fuse_frame(sources, source_weights=weights)
        stats.fused_boxes += len(fused)
        stats.corroborated += sum(1 for b in fused if len(b.supporting_sources) >= 2)
        rows.append({
            "t_seconds": round(t, 4),
            "sources": ["detector", "time"],
            "source_weights": {k: round(v, 4) for k, v in weights.items()},
            "status": "proposed",
            "human_review_required": True,
            "boxes": [b.as_dict() for b in fused],
        })
    return rows


def sample_and_label(
    video_path: str | Path,
    detector,
    target_hz: float = TARGET_HZ,
    stats: DenseStats | None = None,
    max_frames: int | None = None,
) -> list[dict]:
    """Open a video, sample at `target_hz`, and label it. The I/O wrapper around label_sequence."""
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / target_hz)))

    frames, times, index = [], [], 0
    while True:
        ok, image = cap.read()
        if not ok:
            break
        if index % step == 0:
            frames.append(image)
            times.append(index / fps)
            if max_frames is not None and len(frames) >= max_frames:
                break
        index += 1
    cap.release()

    return label_sequence(frames, times, detector, stats)


def label_matches(
    manifest_path: str | Path,
    detector,
    out_dir: str | Path,
    target_hz: float = TARGET_HZ,
) -> DenseStats:
    """Label every match in a downloaded-video manifest, writing one JSONL per match.

    Resumable: a match whose output already exists is skipped, so a long run survives interruption.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats = DenseStats()

    for entry in manifest:
        target = out / f"{entry['match_id']}-dense.jsonl"
        if target.exists():
            continue
        rows = sample_and_label(entry["path"], detector, target_hz, stats)
        tmp = target.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
        tmp.replace(target)
        stats.per_match[entry["match_id"]] = len(rows)

    return stats
