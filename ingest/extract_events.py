"""Derive events for a finished run, and list the moments a human still has to judge.

Adds to what the analyzer wrote rather than replacing it: `match_start` and `match_end` are its
output and stay exactly as they were. The new events are the ones derivable without a model --
phase boundaries from the clock, immobility from track geometry -- plus, when a video is supplied,
the scoreboard's own account of when each alliance scored.

Scoring moments are written to their own file rather than as events, because a point total is not
a shot count. Turning "+5 to red" into a number of `shot_made` needs the season's point values,
and 2026's are all zero placeholders. The file is a worklist: twelve timestamps to check beats
watching two and a half minutes looking for them.

    python -m ingest.extract_events --job data/jobs/<id>/job.json \\
        --tracks data/jobs/<id>/tracks.jsonl --events data/jobs/<id>/events.jsonl \\
        --out data/jobs/<id>/events.derived.jsonl --video data/segments/<clip>.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import action_extraction as actions

SEASONS = Path("contracts/seasons")
SCORE_STEP_SECONDS = 5.0


def read_jsonl(path: Path) -> list[dict]:
    if not path or not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def timer_samples(video_path: Path, step: float = SCORE_STEP_SECONDS
                  ) -> list[tuple[float, int | None]]:
    """Match-clock readings across the clip, for anchoring the match to the video."""
    import cv2

    from .scoreboard import read_match_timer

    capture = cv2.VideoCapture(str(video_path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    wanted = {int(i * step * fps): i * step for i in range(int((total / fps) / step) + 1)}
    out: list[tuple[float, int | None]] = []
    index = 0
    last = max(wanted) if wanted else -1
    while index <= last:
        ok, frame = capture.read()
        if not ok:
            break
        if index in wanted:
            out.append((wanted[index], read_match_timer(frame)))
        index += 1
    capture.release()
    return out


def score_readings(video_path: Path, step: float = SCORE_STEP_SECONDS
                   ) -> dict[str, list[tuple[float, int | None]]]:
    """Sample both alliance scores across the clip."""
    import cv2

    from .scoreboard import read_alliance_scores

    capture = cv2.VideoCapture(str(video_path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    wanted = {int(t * fps): t / 1.0 for t in
              [i * step for i in range(int((total / fps) / step) + 1)]}
    out: dict[str, list[tuple[float, int | None]]] = {"red": [], "blue": []}
    index = 0
    last = max(wanted) if wanted else -1
    while index <= last:
        ok, frame = capture.read()
        if not ok:
            break
        if index in wanted:
            red, blue = read_alliance_scores(frame)
            out["red"].append((wanted[index], red))
            out["blue"].append((wanted[index], blue))
        index += 1
    capture.release()
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--tracks", required=True, type=Path)
    parser.add_argument("--events", type=Path, help="the analyzer's events, carried through")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--video", type=Path, help="read the scoreboard for scoring moments")
    args = parser.parse_args(argv)

    job = json.loads(args.job.read_text(encoding="utf-8"))
    season_path = SEASONS / f"{job['season']}.json"
    config = json.loads(season_path.read_text(encoding="utf-8"))
    tracks = read_jsonl(args.tracks)
    existing = read_jsonl(args.events) if args.events else []

    duration = float(job.get("duration") or 0.0) or max(
        (b["t"] for t in tracks for b in t.get("boxes", [])), default=0.0)

    # Where the match sits inside the clip. Without this every phase boundary is wrong by
    # however much pre-match footage the clip carries, which was 21 seconds on the first real run.
    offset, anchor_note = 0.0, "assumed: the match starts at the beginning of the clip"
    if args.video:
        timer_readings = timer_samples(args.video)
        anchor = actions.match_anchor(timer_readings)
        if anchor is not None:
            zero_at, agreed = anchor
            offset = actions.match_start_offset(zero_at, config)
            anchor_note = (f"read from the match clock: it reaches zero at clip t={zero_at:.0f}s "
                           f"({agreed} readings agreed), so the match starts at t={offset:.0f}s")
        else:
            anchor_note = "the match clock could not be read; falling back to the clip start"
    print(f"match offset {offset:.1f}s -- {anchor_note}\n")

    rows = actions.phase_changes(duration, config, offset)
    for track in tracks:
        rows.extend(actions.immobility_events(track, config, offset))

    derived = actions.to_events(rows, job["job_id"], job["match_id"])
    combined = existing + derived

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for event in combined:
            handle.write(json.dumps(event) + "\n")

    kinds: dict[str, int] = {}
    for event in combined:
        kinds[event["event_type"]] = kinds.get(event["event_type"], 0) + 1
    print(f"{len(existing)} events from the analyzer, {len(derived)} derived here")
    for kind, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:<16} {count}")
    print(f"-> {args.out}")

    if not args.video:
        return 0

    print(f"\nreading the scoreboard every {SCORE_STEP_SECONDS:.0f}s ...")
    readings = score_readings(args.video)
    moments = []
    for alliance in ("red", "blue"):
        got = sum(1 for _, v in readings[alliance] if v is not None)
        timeline = actions.stable_scores(readings[alliance])
        found = actions.scoring_moments(timeline, alliance)
        moments.extend(found)
        final = timeline[-1][1] if timeline else 0
        print(f"  {alliance:>4}: read {got}/{len(readings[alliance])} samples, "
              f"{len(found)} scoring moments, final {final}")

    moments.sort(key=lambda m: m["t_seconds"])
    for moment in moments:
        moment["phase"] = actions.phase_for(
            moment["t_seconds"] - offset, float(config.get("auto_seconds") or 0),
            float(config.get("teleop_seconds") or 0), float(config.get("endgame_seconds") or 0))
        moment["shots"] = actions.shots_from_points(moment["points"], moment["phase"], config)

    worklist = args.out.with_name("scoring-moments.json")
    unknown = sum(1 for m in moments if m["shots"] is None)
    worklist.write_text(json.dumps({
        "match_id": job["match_id"],
        "note": ("Each entry is a confirmed rise in an alliance's score, read off the broadcast. "
                 "'shots' is null wherever the season config's point_values are placeholders, "
                 "which is every entry for 2026 -- a point total is not a shot count, and "
                 "guessing the unit would make every accuracy figure downstream wrong. Fill in "
                 "contracts/seasons/2026.json and this fills itself in."),
        "moments": moments,
    }, indent=2), encoding="utf-8")

    print(f"\n{len(moments)} scoring moments -> {worklist}")
    if unknown:
        print(f"  {unknown} have no shot count: 2026 point_values are all zero placeholders.")
        print("  Fill those in and the shot arithmetic switches itself on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
