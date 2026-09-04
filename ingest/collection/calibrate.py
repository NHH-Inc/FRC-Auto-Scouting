"""Recover a camera's image-to-field mapping from the AprilTags already on the field.

`homography.py` deliberately refuses to guess reference points -- a caller supplies them. This is
that caller. The field's tags are surveyed to the millimetre and published by WPILib, and OpenCV
reads their family natively, so a fixed camera can be calibrated from footage alone with no tape
measure and nobody clicking corners.

Four things have to be got right, and each one fails silently if it is not:

  * **The camera must not move.** A homography belongs to one camera pose. Pooling detections
    across frames is what buys enough tags to be worth checking, and it is only valid while the
    shot is still. Every tag's spread across the sample is measured, and a wandering tag ends the
    calibration rather than being averaged into it.

  * **Tags must share a plane.** The 2026 field puts its 32 tags at three heights, 16 at 3.68 ft,
    8 at 2.92 and 8 at 1.81. Mixing them fits a surface that does not exist. `apriltag_layout`
    already reduces a set of observations to its dominant height; this only has to pass them in.

  * **One camera at a time.** Some 2026 broadcasts stack two views of the same field in one frame,
    and the same physical tag can appear in both. On a real match, four usable tags were in the
    upper view and four in the lower -- fitting across that boundary mixes two cameras. Hence the
    region filter, which is not optional in that footage.

  * **Four points cannot be checked.** Any four points fit a homography exactly, so reprojection
    error is zero by construction and means nothing. Five is where it starts to. The result says
    which case it is instead of reporting a number that looks like evidence.

**What the mapping is to.** The tags sit at a height, so the recovered plane is that height, not
the carpet. A robot's position read through it is the point where its box meets that plane, which
is offset from where the robot actually stands by an amount that grows with camera angle. Good
enough to say which end of the field a robot is in and roughly how fast it crossed; not good
enough to call a foul over. `plane_height_ft` in the output records it so nobody has to guess.

    python -m ingest.collection.calibrate --video data/segments/<clip>.mp4 \\
        --out analysis/config/homography.<venue>.json --region 0.0 0.68
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from .apriltag_layout import correspondences_from_observations, load_layout

#: Frames to sample across the clip. Tags are occluded by robots constantly, so more samples find
#: more tags; past a point it only costs time.
SAMPLES = 40

#: The detector struggles with a broadcast-sized tag at native resolution -- 3 tags found against
#: 12 at double size on the same frame.
UPSCALE = 2

#: Pixels a tag's centre may wander across the sample and still be one fixed point. Sub-pixel is
#: what a static camera actually gives: on a real match every usable tag came in under 1 px.
MAX_DRIFT_PX = 12.0

#: Sightings below which a tag is a coincidence rather than an observation.
MIN_SIGHTINGS = 3

DEFAULT_LAYOUT = Path("contracts/fields/2026-apriltags.json")


@dataclass
class TagSighting:
    tag_id: int
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)

    def median(self) -> tuple[float, float]:
        import statistics

        return statistics.median(self.xs), statistics.median(self.ys)

    def drift(self) -> float:
        """Furthest a sighting fell from the median, in pixels."""
        import math

        mx, my = self.median()
        return max((math.hypot(x - mx, y - my) for x, y in zip(self.xs, self.ys)), default=0.0)


def build_detector():
    """An OpenCV detector tuned for tags that are small and compressed rather than printed and near."""
    import cv2

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36H11)
    params = cv2.aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 43
    params.adaptiveThreshWinSizeStep = 4
    params.minMarkerPerimeterRate = 0.005
    params.polygonalApproxAccuracyRate = 0.06
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(dictionary, params)


def gather_sightings(video_path, samples=SAMPLES, region=(0.0, 1.0), upscale=UPSCALE
                     ) -> tuple[dict[int, TagSighting], int]:
    """Detect tags across the clip. Returns (sightings by tag id, frames actually read)."""
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        capture.release()
        return {}, 0
    # Skip the ends: intros, replays and award cards are not the match camera.
    wanted = {int(total * (0.08 + 0.84 * i / max(1, samples - 1))) for i in range(samples)}
    detector = build_detector()

    sightings: dict[int, TagSighting] = {}
    index, frames = 0, 0
    last = max(wanted)
    while index <= last:
        ok, frame = capture.read()
        if not ok:
            break
        if index in wanted:
            frames += 1
            height = frame.shape[0]
            grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            image = cv2.resize(grey, None, fx=upscale, fy=upscale,
                               interpolation=cv2.INTER_CUBIC) if upscale != 1 else grey
            corners, ids, _ = detector.detectMarkers(image)
            for corner, tag_id in zip(corners, (ids.flatten() if ids is not None else [])):
                centre = corner.reshape(4, 2).mean(axis=0) / upscale
                if not (region[0] <= centre[1] / height < region[1]):
                    continue      # a different camera's view of the same field
                seen = sightings.setdefault(int(tag_id), TagSighting(int(tag_id)))
                seen.xs.append(float(centre[0]))
                seen.ys.append(float(centre[1]))
        index += 1
    capture.release()
    return sightings, frames


def steady_tags(sightings: dict[int, TagSighting], max_drift=MAX_DRIFT_PX,
                min_sightings=MIN_SIGHTINGS) -> tuple[dict[int, tuple[float, float]], list[str]]:
    """Tags that held still. Returns (id -> median pixel, reasons others were dropped)."""
    kept: dict[int, tuple[float, float]] = {}
    notes: list[str] = []
    for tag_id, seen in sorted(sightings.items()):
        if len(seen.xs) < min_sightings:
            notes.append(f"tag {tag_id}: only {len(seen.xs)} sightings")
            continue
        drift = seen.drift()
        if drift > max_drift:
            # Either the camera panned or the detection is unreliable. Averaging either one
            # produces a confident point that was never there.
            notes.append(f"tag {tag_id}: drifts {drift:.1f}px, camera is not static")
            continue
        kept[tag_id] = seen.median()
    return kept, notes


def calibrate(video_path, layout_path=DEFAULT_LAYOUT, samples=SAMPLES, region=(0.0, 1.0),
              extra_points=()) -> dict:
    """Everything needed to write a calibration file, plus why it should or should not be trusted."""
    from . import homography as homography_module

    layout = load_layout(layout_path)
    sightings, frames = gather_sightings(video_path, samples=samples, region=region)
    observed, notes = steady_tags(sightings)

    pairs = correspondences_from_observations(layout, observed, require_coplanar=True)
    # Extra correspondences a human measured, for footage where the tags alone cannot reach the
    # five points that make reprojection error mean anything.
    pairs = list(pairs) + [((p["image"][0], p["image"][1]), (p["field"][0], p["field"][1]))
                           for p in extra_points]

    used_ids = sorted(
        tag_id for tag_id in observed
        if tag_id in layout.tags
        and any(abs(layout.tags[tag_id].x_ft - f[0]) < 1e-9 and
                abs(layout.tags[tag_id].y_ft - f[1]) < 1e-9 for _, f in pairs)
    )
    plane_heights = {layout.tags[t].z_ft for t in used_ids}

    result = {
        "frames_sampled": frames,
        "tags_detected": sorted(sightings),
        "tags_steady": sorted(observed),
        "tags_used": used_ids,
        "notes": notes,
        "point_count": len(pairs),
        "plane_height_ft": round(min(plane_heights), 3) if plane_heights else None,
        "points": [{"image": [round(i[0], 2), round(i[1], 2)],
                    "field": [round(f[0], 4), round(f[1], 4)]} for i, f in pairs],
        "solution": None,
    }
    if len(pairs) < 4:
        return result

    solved = homography_module.solve([p[0] for p in pairs], [p[1] for p in pairs],
                                     layout.length_ft, layout.width_ft)
    if solved is not None:
        result["solution"] = {
            "reprojection_ft": round(solved.reprojection_ft, 4),
            "has_redundancy": solved.has_redundancy,
            "trustworthy": solved.trustworthy,
        }
    return result



def write_reference_frame(video_path, out_path, region=(0.0, 1.0), observed=None) -> bool:
    """Save a frame with a pixel grid and the detected tags marked.

    Written whenever calibration cannot finish, because the fix is always the same: a person has
    to supply image points for field features they can identify. Reading a pixel coordinate off a
    gridded image is a two-minute job; guessing one is not.
    """
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    target = int(total * 0.5)
    frame = None
    for i in range(target + 1):
        ok, image = capture.read()
        if not ok:
            break
        if i == target:
            frame = image
    capture.release()
    if frame is None:
        return False

    height, width = frame.shape[:2]
    for x in range(0, width, 100):
        heavy = x % 500 == 0
        cv2.line(frame, (x, 0), (x, height), (0, 255, 255), 2 if heavy else 1)
        if heavy:
            cv2.putText(frame, str(x), (x + 4, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    for y in range(0, height, 100):
        heavy = y % 500 == 0
        cv2.line(frame, (0, y), (width, y), (0, 255, 255), 2 if heavy else 1)
        if heavy:
            cv2.putText(frame, str(y), (6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    # The searched band, so it is obvious when a stacked second view was excluded.
    for edge in region:
        cv2.line(frame, (0, int(height * edge)), (width, int(height * edge)), (255, 0, 255), 3)

    for tag_id, (x, y) in (observed or {}).items():
        cv2.circle(frame, (int(x), int(y)), 14, (0, 255, 0), 3)
        cv2.putText(frame, f"tag {tag_id}", (int(x) + 16, int(y) + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), frame)
    return True


EXTRA_POINTS_TEMPLATE = """[
  {"_comment": "Pixel coordinates read off the reference frame, paired with where that feature is on the field in feet. Origin is a field corner: x runs along the 54.27 ft length, y across the 26.47 ft width. Delete this comment entry."},
  {"image": [0, 0], "field": [0.0, 0.0]},
  {"image": [0, 0], "field": [54.27, 0.0]},
  {"image": [0, 0], "field": [54.27, 26.47]},
  {"image": [0, 0], "field": [0.0, 26.47]}
]
"""

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--samples", type=int, default=SAMPLES)
    parser.add_argument("--region", nargs=2, type=float, default=[0.0, 1.0],
                        metavar=("TOP", "BOTTOM"),
                        help="fraction of frame height to search; use this when a broadcast "
                             "stacks two camera views, or tags from both get mixed into one fit")
    parser.add_argument("--extra-points", type=Path,
                        help="JSON list of {image:[x,y], field:[ft,ft]} measured by hand, to "
                             "reach the five points that make reprojection error meaningful")
    args = parser.parse_args(argv)

    extra = []
    if args.extra_points:
        extra = json.loads(args.extra_points.read_text(encoding="utf-8"))

    result = calibrate(args.video, args.layout, args.samples, tuple(args.region), extra)

    print(f"{result['frames_sampled']} frames sampled from y {args.region[0]}-{args.region[1]}")
    print(f"  tags detected : {result['tags_detected']}")
    print(f"  held still    : {result['tags_steady']}")
    print(f"  coplanar, used: {result['tags_used']}")
    for note in result["notes"]:
        print(f"  ! {note}")

    def rescue(reason: str) -> int:
        reference = args.out.with_suffix(".reference.png")
        template = args.out.with_suffix(".extra-points.json")
        observed = {t: tuple(p["image"]) for t, p in
                    zip(result["tags_used"], result["points"])}
        print(f"\n{reason}")
        if write_reference_frame(args.video, reference, tuple(args.region), observed):
            print(f"  reference frame: {reference}")
        if not template.exists():
            template.write_text(EXTRA_POINTS_TEMPLATE, encoding="utf-8")
            print(f"  template       : {template}")
        print("  Read pixel coordinates for field features you can identify off the grid, fill "
              "them into the template, and re-run with --extra-points.")
        return 1

    if result["point_count"] < 4:
        return rescue(f"only {result['point_count']} usable correspondences; four is the minimum.")

    height = result["plane_height_ft"]
    print(f"\n{result['point_count']} correspondences on the plane at {height} ft")
    solution = result["solution"]
    if solution is None:
        return rescue(
            "the points are degenerate -- they lie on a line, so they cannot define a plane. "
            "On this footage all four coplanar tags sit within 0.1px of one image row, because "
            "both goal structures carry them at the same height and the camera looks down the "
            "field at them. Tags alone cannot calibrate this angle.")

    print(f"  reprojection : {solution['reprojection_ft']} ft")
    if solution["has_redundancy"]:
        print(f"  trustworthy  : {solution['trustworthy']}")
    else:
        print("  UNVERIFIED: four points fit exactly, so this error is zero by construction and "
              "is not evidence. Add a fifth with --extra-points to make it mean something.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "_comment": (f"Auto-calibrated from {Path(args.video).name} using AprilTags "
                     f"{result['tags_used']}. Maps to the plane {height} ft above the carpet, "
                     f"where the tags are -- NOT the floor. Positions read through it are offset "
                     f"from where a robot actually stands by an amount that grows with camera "
                     f"angle. One camera pose only; re-run per venue and per camera position."),
        "plane_height_ft": height,
        "has_redundancy": solution["has_redundancy"],
        "reprojection_ft": solution["reprojection_ft"],
        "points": result["points"],
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(f"Use it with:  $env:FRC_HOMOGRAPHY_CONFIG = "
          f'(Resolve-Path "{args.out}").Path')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
