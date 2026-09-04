"""Build a pack of frames for humans to label, from footage the detector is weak on.

Every other labelling tool here starts from what the detector found and asks a human to confirm
it. This one exists for the opposite case: a viewpoint the detector does not recognise at all.
Measured on real 2026 footage, robots in the second of the two stacked camera views are missed at
`score_threshold` 0.35, at 0.05, under tiled inference, and at 3x magnification -- zero boxes
where a person sees several. The machine labelling loop cannot help, because it cannot propose
what it cannot see. Only people can start this one.

It matters more than one venue's quirk. Every 2026 broadcast sampled has the same stacked layout,
and detection is thin across all of them -- one to five robots per frame where six are playing.
The footage Tengen is actually being built for is worse still: shot from the stands rather than
by a broadcast crew, which is further from the 2023-24 training images than any of this.

Three rules, each one learned the expensive way:

  * **Every robot in the frame, or the frame is poison.** A detector treats unlabelled pixels as
    background, so a frame with four robots boxed and two missed does not merely fail to teach --
    it teaches that robots are background. This is why the instructions are blunt and why a
    labeller may mark a frame `skip` instead of doing it half way.
  * **Venue count buys generalisation, not frame count.** Thresholds tuned on ten venues did not
    survive twenty-five. Frames are drawn round-robin across segments so a pack is never mostly
    one arena.
  * **Proposals are a starting point, never an answer.** The current detector's boxes are written
    in so a labeller corrects rather than draws from scratch, but every frame is marked
    `human_review_required` and the pack records which model produced them.

Output is a YOLO-format folder, which Roboflow, CVAT and LabelImg all import directly.

    python -m ingest.collection.label_pack --segments data/segments --out data/label-packs/v3 \\
        --frames 400 --model data/robot-v2.onnx
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

#: Seconds between frames taken from one segment. Consecutive broadcast frames are near-identical,
#: so a pack of neighbours is one moment labelled many times rather than many moments.
MIN_GAP_SECONDS = 8.0

#: Skip the first and last of a clip: intros, replays and "ALLIANCE WINS" cards live there.
SKIP_HEAD_SHARE = 0.10
SKIP_TAIL_SHARE = 0.08

#: Confidence for the pre-filled proposals. Deliberately lower than the analyzer runs at -- a
#: labeller deleting a wrong box is faster than drawing a missing one, so recall is what helps.
PROPOSAL_CONFIDENCE = 0.25


@dataclass
class PackStats:
    segments: int = 0
    frames_written: int = 0
    frames_rejected: int = 0
    proposals: int = 0
    frames_without_proposals: int = 0
    rejected_reasons: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.frames_rejected += 1
        self.rejected_reasons[reason] = self.rejected_reasons.get(reason, 0) + 1


def sample_times(duration: float, wanted: int, gap: float = MIN_GAP_SECONDS) -> list[float]:
    """Evenly spread timestamps inside a clip, never closer together than `gap`."""
    if duration <= 0 or wanted <= 0:
        return []
    start = duration * SKIP_HEAD_SHARE
    end = duration * (1.0 - SKIP_TAIL_SHARE)
    if end <= start:
        return []
    usable = end - start
    count = min(wanted, max(1, int(usable // gap) + 1))
    if count == 1:
        return [start + usable / 2.0]
    step = usable / (count - 1)
    return [start + step * i for i in range(count)]


def plan_frames(durations: dict[str, float], total: int, gap: float = MIN_GAP_SECONDS
                ) -> list[tuple[str, float]]:
    """Which (segment, timestamp) pairs to grab, spread round-robin across segments.

    Round-robin rather than segment-by-segment because a pack that runs out of budget partway
    should still cover every venue. Twenty-five venues at four frames each generalises better
    than four venues at twenty-five, and that is not a guess -- thresholds tuned on ten venues
    here failed on twenty-five.
    """
    if total <= 0 or not durations:
        return []
    per_segment = {name: sample_times(duration, total, gap)
                   for name, duration in sorted(durations.items())}
    plan: list[tuple[str, float]] = []
    index = 0
    while len(plan) < total:
        added = False
        for name in sorted(per_segment):
            times = per_segment[name]
            if index < len(times):
                plan.append((name, times[index]))
                added = True
                if len(plan) >= total:
                    break
        if not added:
            break          # every segment exhausted before the budget was
        index += 1
    return plan


def yolo_line(box: dict, class_id: int = 0) -> str:
    """A normalised centre-and-size line, which is what YOLO training expects."""
    cx = box["x"] + box["w"] / 2.0
    cy = box["y"] + box["h"] / 2.0
    return f"{class_id} {cx:.6f} {cy:.6f} {box['w']:.6f} {box['h']:.6f}"


INSTRUCTIONS = """# Labelling pack for Project Tengen

Thank you -- this is the one job in the project a machine genuinely cannot start.

## What to do

Draw a box around **every robot** in each image. One class: `robot`.

Some boxes are already drawn. They came from our current detector, which is often wrong and
frequently misses robots entirely. **Correct them.** Move them, resize them, delete the wrong
ones, and add the ones it missed.

## The one rule that really matters

**Box every robot you can see, or skip the image entirely.**

A half-labelled image is worse than no image. The training treats anything you did not box as
"definitely not a robot", so an image with four robots boxed and two missed actively teaches the
model that robots are background. That is how a model gets *worse* after training on more data,
and it has happened to this project before.

If an image is too messy, too blurry, or you are not sure -- **skip it**. Skipping costs us
nothing. Guessing costs us the model.

## What counts as a robot

- **Yes:** any competition robot, anywhere in the picture, including in the smaller second camera
  view at the bottom of most frames. Those are the ones our detector is blindest to, so they are
  the most valuable boxes in the pack.
- **Yes:** robots that are partly hidden behind a field wall, another robot, or a person -- box
  the part you can see.
- **Yes:** robots in the driver-station or starting areas.
- **No:** field elements, goals, game pieces (the yellow balls), carts, people.
- **No:** a robot on a screen inside the picture (a jumbotron showing the match). If you cannot
  tell, skip the image.

## How tight

Around the robot's actual extent including its bumpers, not its shadow and not the game pieces
it is carrying. Close is fine -- a few pixels either way does not matter. Missing a robot does.

## Format

YOLO. One `.txt` per image in `labels/`, same filename. An image with no robots gets an empty
`.txt` file -- that is a real and useful label, not a mistake.
"""


def build(source_frames, out_dir: Path, detector=None, stats: PackStats | None = None,
          quality_check=None) -> PackStats:
    """Write a pack from an iterable of (name, timestamp, image) triples.

    Separated from video decoding so the selection and writing rules can be tested with plain
    arrays rather than a multi-gigabyte clip.
    """
    import cv2

    stats = stats or PackStats()
    images = out_dir / "images"
    labels = out_dir / "labels"
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    manifest = []

    for name, seconds, image in source_frames:
        if image is None or getattr(image, "size", 0) == 0:
            stats.reject("unreadable")
            continue
        if quality_check is not None:
            verdict = quality_check(image)
            if not getattr(verdict, "usable", True):
                # Broadcast graphics, replays and score cards teach nothing about robots.
                stats.reject(getattr(verdict, "reason", "unusable") or "unusable")
                continue

        stem = f"{name}_{int(round(seconds * 1000)):08d}"
        cv2.imwrite(str(images / f"{stem}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 92])

        boxes = detector.detect(image) if detector is not None else []
        (labels / f"{stem}.txt").write_text(
            "\n".join(yolo_line(b) for b in boxes) + ("\n" if boxes else ""), encoding="utf-8")
        stats.proposals += len(boxes)
        if not boxes:
            stats.frames_without_proposals += 1
        stats.frames_written += 1
        manifest.append({
            "image": f"images/{stem}.jpg",
            "label": f"labels/{stem}.txt",
            "segment": name,
            "t_seconds": round(seconds, 3),
            "proposals": len(boxes),
            "status": "proposed",
            "human_review_required": True,
        })

    (out_dir / "README.md").write_text(INSTRUCTIONS, encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps({
        "schema_version": 3,
        "frames": len(manifest),
        "proposals": stats.proposals,
        "frames_without_proposals": stats.frames_without_proposals,
        "note": ("Proposals came from a detector known to miss robots. Every frame needs a human "
                 "to add what it missed; a partly-labelled frame teaches that robots are "
                 "background."),
        "items": manifest,
    }, indent=2), encoding="utf-8")
    (out_dir / "data.yaml").write_text(
        "path: .\ntrain: images\nval: images\nnc: 1\nnames: [robot]\n", encoding="utf-8")
    return stats


def frames_from_videos(segments: Path, plan: list[tuple[str, float]]):
    """Decode the planned frames, reading each clip once and never seeking.

    Seeking H.264 lands on the nearest keyframe, so a timestamp would silently name a different
    image than the one written -- the sort of error that only shows up as unexplained label noise
    much later.
    """
    import cv2

    by_segment: dict[str, list[float]] = {}
    for name, seconds in plan:
        by_segment.setdefault(name, []).append(seconds)

    for name in sorted(by_segment):
        path = segments / f"{name}.mp4"
        if not path.is_file():
            continue
        capture = cv2.VideoCapture(str(path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        wanted = sorted({int(round(s * fps)): s for s in by_segment[name]}.items())
        targets = dict(wanted)
        index, last = 0, (max(targets) if targets else -1)
        while index <= last:
            ok, frame = capture.read()
            if not ok:
                break
            if index in targets:
                yield name, targets[index], frame
            index += 1
        capture.release()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--segments", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--frames", type=int, default=400)
    parser.add_argument("--model", type=Path, default=None,
                        help="ONNX detector for pre-filled proposals; omit for empty labels")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    import cv2

    from .frame_quality import measure_image

    clips = sorted(args.segments.glob("*.mp4"))
    if not clips:
        print(f"no .mp4 segments under {args.segments}")
        return 1

    durations = {}
    for path in clips:
        capture = cv2.VideoCapture(str(path))
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        capture.release()
        if fps > 0 and count > 0:
            durations[path.stem] = count / fps

    random.seed(args.seed)
    plan = plan_frames(durations, args.frames)
    print(f"{len(durations)} segments, planning {len(plan)} frames "
          f"({len({n for n, _ in plan})} venues covered)")

    detector = None
    if args.model:
        from .detect_runner import OnnxDetector
        detector = OnnxDetector(model_path=str(args.model),
                                confidence_threshold=PROPOSAL_CONFIDENCE)

    stats = PackStats(segments=len(durations))
    build(frames_from_videos(args.segments, plan), args.out,
          detector=detector, stats=stats, quality_check=measure_image)

    print(f"\nwrote {stats.frames_written} frames to {args.out}")
    print(f"  {stats.proposals} proposed boxes "
          f"({stats.proposals / max(1, stats.frames_written):.1f} per frame)")
    print(f"  {stats.frames_without_proposals} frames the detector found nothing in "
          f"-- those need a human most")
    if stats.rejected_reasons:
        print(f"  {stats.frames_rejected} rejected: " +
              ", ".join(f"{k} {v}" for k, v in sorted(stats.rejected_reasons.items())))
    print(f"\nHand out {args.out}. The rule that matters is in its README: every robot in the "
          f"frame, or skip the frame.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
