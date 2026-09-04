"""Fill in `team`, `alliance` and `team_confidence` on a run's tracks.

Reads the roster off the scoreboard when the job has no TBA alliances, reads the bumpers, votes
per track, and writes a new tracks file. The input is never modified: doc 0 is explicit that raw
model output stays untouched and that corrections live beside it, and an attribution that turns
out to be wrong must not have destroyed what the model actually said.

A human overrides any of this in the web app -- PATCH a track's team and every event on it moves
in one action, `?raw=true` still returns the original, and deleting the correction undoes it. So
the bar for writing an attribution here is "confident enough to be a useful default", not
"certain": a wrong one costs a click, while a missing one costs nothing but a click too.

    python -m ingest.attribute_tracks --job data/jobs/<id>/job.json \\
        --tracks data/jobs/<id>/tracks.jsonl --out data/jobs/<id>/tracks.attributed.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from . import scoreboard
from .team_id import crop_for, decide_alliance, read_bumper, tally_track, tesseract_available

#: Where in the match to sample the scoreboard. Spread out so a replay or a graphic covering the
#: bar on one sample cannot decide the roster.
ROSTER_SAMPLES = 8
#: Cap the reads per track. A hundred is far more than voting needs and each one costs an OCR
#: call, so long tracks are sampled rather than read exhaustively.
MAX_READS_PER_TRACK = 60


def roster_for(job: dict, video_path: Path, duration: float, fps: float) -> tuple[dict, str]:
    """(roster, where it came from). TBA when it has the match, the scoreboard otherwise."""
    alliances = job.get("alliances")
    if isinstance(alliances, dict) and alliances.get("red") and alliances.get("blue"):
        return {"red": sorted(alliances["red"]), "blue": sorted(alliances["blue"])}, "tba"
    step = duration / (ROSTER_SAMPLES + 1)
    times = [step * (i + 1) for i in range(ROSTER_SAMPLES)]
    return scoreboard.read_roster(video_path, times, fps), "scoreboard_ocr"


def gather_reads(video_path: Path, tracks: list[dict], fps: float) -> dict[int, tuple]:
    """{track_id: (alliance observations, digit reads)} in one pass over the video."""
    import cv2

    wanted: dict[int, list] = defaultdict(list)
    for track in tracks:
        boxes = track["boxes"]
        step = max(1, len(boxes) // MAX_READS_PER_TRACK)
        for box in boxes[::step]:
            wanted[int(round(box["t"] * fps))].append((track["track_id"], box))

    colours: dict[int, list] = defaultdict(list)
    reads: dict[int, list] = defaultdict(list)
    if not wanted:
        return {}

    capture = cv2.VideoCapture(str(video_path))
    index, last = 0, max(wanted)
    while index <= last:
        ok, frame = capture.read()
        if not ok:
            break
        for track_id, box in wanted.get(index, ()):
            patch = crop_for(frame, box)
            if patch.size == 0:
                continue
            alliance, digits = read_bumper(patch)
            colours[track_id].append(alliance)
            reads[track_id].extend(digits)
        index += 1
    capture.release()
    return {t["track_id"]: (colours[t["track_id"]], reads[t["track_id"]]) for t in tracks}


def attribute(tracks: list[dict], gathered: dict, roster: dict) -> list[dict]:
    """A new list of tracks with team, alliance and team_confidence filled in."""
    out = []
    for track in tracks:
        updated = dict(track)
        observations, reads = gathered.get(track["track_id"], ([], []))
        alliance = decide_alliance(observations)
        vote = tally_track(reads, alliance, roster)
        team, confidence = vote.resolve()
        updated["alliance"] = alliance
        updated["team"] = team
        updated["team_confidence"] = confidence if team is not None else None
        out.append(updated)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--tracks", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    if not tesseract_available():
        print("Tesseract is not available, so no bumper can be read. Every track will stay "
              "unattributed, which is the honest result -- set TESSERACT_CMD or install it.")

    job = json.loads(args.job.read_text(encoding="utf-8"))
    tracks = [json.loads(l) for l in args.tracks.read_text(encoding="utf-8").splitlines() if l.strip()]
    video = Path(job["local_path"])
    if not video.is_file():
        print(f"video not found: {video}")
        return 1

    fps = float(job.get("fps") or 30.0)
    duration = float(job.get("duration") or 0.0) or (max(
        (b["t"] for t in tracks for b in t["boxes"]), default=0.0) + 1.0)

    roster, source = roster_for(job, video, duration, fps)
    print(f"roster ({source}): red {roster['red']}  blue {roster['blue']}")
    if not roster["red"] and not roster["blue"]:
        print("no roster, so nothing constrains the reads; every track will stay unattributed")

    gathered = gather_reads(video, tracks, fps)
    attributed = attribute(tracks, gathered, roster)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for track in attributed:
            handle.write(json.dumps(track) + "\n")

    named = sum(1 for t in attributed if t["team"] is not None)
    print(f"\n{'track':>6} {'boxes':>6} {'alliance':>9} {'team':>7} {'conf':>6}")
    for track in sorted(attributed, key=lambda t: -len(t["boxes"])):
        conf = track["team_confidence"]
        print(f"{track['track_id']:>6} {len(track['boxes']):>6} {str(track['alliance']):>9} "
              f"{str(track['team']):>7} {'' if conf is None else f'{conf:>6.2f}'}")
    print(f"\n{named} of {len(attributed)} tracks attributed -> {args.out}")
    print("Anything wrong or missing is one PATCH away in the web app, and that moves every "
          "event on the track at once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
