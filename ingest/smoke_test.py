"""Contract E smoke test, SCHEMA_VERSION 2.

Seeds the golden fixtures straight into the database and drives every endpoint component 3
calls. No network, no yt-dlp, no analysis binary -- doc 0: "Component 2 tests the pipeline
with a stub binary that copies the fixture output."

Run from the repo root:

    ingest\\.venv\\Scripts\\python -m ingest.smoke_test        (Windows / PowerShell)
    ingest/.venv/bin/python -m ingest.smoke_test              (POSIX)
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"
MAIN = FIXTURES / "2026casf_qm42"
NO_TBA = FIXTURES / "2026casf_qm43_no_tba"

# Must be set before ingest.database is imported -- the engine is built at import time.
_tmp = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'smoke.db').as_posix()}"
os.environ["FRC_DATA_DIR"] = str(_tmp / "data")

from fastapi.testclient import TestClient  # noqa: E402

from ingest import database, models  # noqa: E402
from ingest.main import app  # noqa: E402

MATCH = "2026casf_qm42"
NO_TBA_MATCH = "2026casf_qm43"

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f" -- {detail}" if detail else ""))


def jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _segment_copy() -> Path:
    """A COPY: deleting a job removes its cached segment (doc 2: media is a cache, not a
    record), and pointing at the fixture would delete the golden video."""
    dest = _tmp / "segment.mp4"
    src = MAIN / "segment.mp4"
    if src.exists():
        shutil.copy2(src, dest)
    else:
        dest.write_bytes(b"")
    return dest


def seed_dir(db, base: Path, local_path: str | None):
    job_data = json.loads((base / "job.json").read_text(encoding="utf-8"))
    db.add(
        models.Job(
            job_id=job_data["job_id"],
            match_id=job_data["match_id"],
            season=job_data["season"],
            video_id=job_data["video_id"],
            local_path=local_path,
            start_offset=job_data["start_offset"],
            duration=job_data["duration"],
            fps=job_data["fps"],
            width=job_data["width"],
            height=job_data["height"],
            status=job_data["status"],
            error_code=job_data["error_code"],
            error=job_data["error"],
            attempt=job_data["attempt"],
            alliances=job_data["alliances"],
            tba_score=job_data["tba_score"],
        )
    )
    if job_data["status"] == "failed":
        return job_data
    for row in jsonl(base / "events.jsonl"):
        db.add(models.Event(**{k: row[k] for k in (
            "event_id", "schema_version", "job_id", "match_id", "team", "track_id",
            "t_seconds", "phase", "event_type", "confidence", "field_x", "field_y", "source")}))
    for row in jsonl(base / "tracks.jsonl"):
        db.add(
            models.Track(
                job_id=job_data["job_id"],
                match_id=job_data["match_id"],  # from the JOB, never the track JSON
                track_id=row["track_id"],
                team=row["team"],
                alliance=row["alliance"],
                team_confidence=row["team_confidence"],
                boxes=row["boxes"],
                gaps=row["gaps"],
            )
        )
    # result.json is read off disk by the API, so put it where the orchestrator would.
    out = Path(os.environ["FRC_DATA_DIR"]) / "jobs" / job_data["job_id"]
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base / "result.json", out / "result.json")
    return job_data


def main():
    db = database.SessionLocal()
    main_job = seed_dir(db, MAIN, str(_segment_copy()))
    seed_dir(db, NO_TBA, None)
    seed_dir(db, FIXTURES / "failed_download", None)
    db.commit()
    db.close()

    client = TestClient(app)
    raw_count = len(jsonl(MAIN / "events.jsonl"))
    track_count = len(jsonl(MAIN / "tracks.jsonl"))

    print("\nContract E envelopes and job records")
    r = client.get("/api/jobs")
    body = r.json()
    check("GET /api/jobs returns an object, not a bare array", isinstance(body, dict) and "jobs" in body)
    check("all three fixture jobs load", len(body["jobs"]) == 3, str(len(body.get("jobs", []))))
    job = next(j for j in body["jobs"] if j["job_id"] == main_job["job_id"])
    check("job carries season", job["season"] == 2026)
    check("job carries attempt + timestamps", job["attempt"] >= 1 and job["updated_at"].endswith("Z"))
    check("schema_version is 2", job["schema_version"] == 2)

    failed_job = next(j for j in body["jobs"] if j["status"] == "failed")
    check("failed job carries an error_code", failed_job["error_code"] == "rate_limited",
          str(failed_job.get("error_code")))

    print("\nEvents and tracks")
    r = client.get(f"/api/matches/{MATCH}/events")
    check("events envelope", "events" in r.json() and len(r.json()["events"]) == raw_count)
    ev = r.json()["events"][0]
    check("event carries corrected + correction_id", "corrected" in ev and "correction_id" in ev)

    r = client.get(f"/api/matches/{MATCH}/tracks")
    tr = r.json()
    check("tracks envelope carries box_sample_rate", tr.get("box_sample_rate") == 5.0,
          str(tr.get("box_sample_rate")))
    check("all tracks returned", len(tr["tracks"]) == track_count, str(len(tr.get("tracks", []))))
    check("track carries team_confidence", "team_confidence" in tr["tracks"][0])
    gapped = [t for t in tr["tracks"] if t.get("gaps")]
    check("gaps survive to the API", len(gapped) > 0 and gapped[0]["gaps"][0]["reason"] in
          {"shot_change", "occlusion", "out_of_frame", "detection_lost"})

    r = client.get(f"/api/jobs/{main_job['job_id']}/result")
    check("GET /api/jobs/:id/result", r.status_code == 200 and r.json()["box_sample_rate"] == 5.0)

    print("\nAccuracy")
    r = client.get(f"/api/matches/{MATCH}/accuracy")
    acc = r.json()
    check("accuracy reports tba_available", acc.get("tba_available") is True)
    r = client.get(f"/api/matches/{NO_TBA_MATCH}/accuracy")
    check("no-TBA match reports tba_available false", r.json().get("tba_available") is False)
    check("no-TBA match has null delta", r.json().get("delta") is None)

    print("\nCorrections never overwrite raw output")
    target = client.get(f"/api/matches/{MATCH}/events").json()["events"][1]
    original_team = target["team"]
    new_team = 1678 if original_team != 1678 else 254

    r = client.patch(f"/api/events/{target['event_id']}", json={"team": new_team})
    check("PATCH event", r.status_code == 200 and r.json()["team"] == new_team, r.text[:120])
    check("patched event is flagged corrected", r.json().get("corrected") is True)

    raw_rows = {e["event_id"]: e for e in client.get(f"/api/matches/{MATCH}/events?raw=true").json()["events"]}
    check("?raw=true still reports the ORIGINAL team",
          raw_rows[target["event_id"]]["team"] == original_team,
          f"raw says {raw_rows[target['event_id']]['team']}, expected {original_team}")

    print("\nTrack-level correction (doc 3's primary path)")
    tracks = client.get(f"/api/matches/{MATCH}/tracks").json()["tracks"]
    victim = next(t for t in tracks if t["team"] is not None)
    before_events = [
        e for e in client.get(f"/api/matches/{MATCH}/events").json()["events"]
        if e["track_id"] == victim["track_id"]
    ]
    r = client.patch(
        f"/api/jobs/{main_job['job_id']}/tracks/{victim['track_id']}", json={"team": 9999}
    )
    check("PATCH track", r.status_code == 200, r.text[:140])
    after_tracks = client.get(f"/api/matches/{MATCH}/tracks").json()["tracks"]
    moved = next(t for t in after_tracks if t["track_id"] == victim["track_id"])
    check("track itself is re-attributed", moved["team"] == 9999, str(moved["team"]))
    after_events = [
        e for e in client.get(f"/api/matches/{MATCH}/events").json()["events"]
        if e["track_id"] == victim["track_id"]
    ]
    check(f"all {len(before_events)} events on the track moved in one action",
          len(after_events) == len(before_events)
          and all(e["team"] == 9999 for e in after_events),
          str({e["team"] for e in after_events}))
    raw_after = [
        e for e in client.get(f"/api/matches/{MATCH}/events?raw=true").json()["events"]
        if e["track_id"] == victim["track_id"]
    ]
    check("raw output is untouched by the track correction",
          all(e["team"] == victim["team"] for e in raw_after))
    raw_tracks = client.get(f"/api/matches/{MATCH}/tracks?raw=true").json()["tracks"]
    check("raw=true on /tracks returns the original attribution",
          next(t for t in raw_tracks if t["track_id"] == victim["track_id"])["team"] == victim["team"])

    print("\nCorrection listing and undo")
    r = client.get(f"/api/matches/{MATCH}/corrections")
    corrections = r.json()["corrections"]
    check("GET corrections envelope", isinstance(corrections, list) and len(corrections) == 2)
    track_corr = next(c for c in corrections if c["scope"] == "track")
    check("track correction carries job_id + target_id",
          track_corr["job_id"] == main_job["job_id"] and track_corr["target_id"] == str(victim["track_id"]))

    r = client.delete(f"/api/corrections/{track_corr['correction_id']}")
    check("DELETE /api/corrections/:id", r.status_code == 204, str(r.status_code))
    restored = client.get(f"/api/matches/{MATCH}/tracks").json()["tracks"]
    check("undo restores the original attribution",
          next(t for t in restored if t["track_id"] == victim["track_id"])["team"] == victim["team"])

    print("\nManual events, deletes, enums")
    r = client.post("/api/events", json={
        "job_id": main_job["job_id"], "match_id": MATCH, "team": 254, "track_id": 7,
        "t_seconds": 63.5, "phase": "teleop", "event_type": "shot_made",
        "confidence": 1.0, "field_x": None, "field_y": None, "source": "manual",
    })
    check("POST /api/events", r.status_code == 200, r.text[:160])
    check("manual event id is a UUID", len(r.json()["event_id"]) == 36)
    check("manual event is NOT in raw output",
          len(client.get(f"/api/matches/{MATCH}/events?raw=true").json()["events"]) == raw_count)

    r = client.post("/api/events", json={"match_id": MATCH, "phase": "halftime"})
    check("unknown enum value is rejected", r.status_code == 400, str(r.status_code))
    check("error response carries error_code + error",
          "error" in r.json(), str(r.json())[:100])

    r = client.delete(f"/api/events/{target['event_id']}")
    check("DELETE /api/events/:id", r.status_code == 204, str(r.status_code))
    check("deleted event survives in raw",
          target["event_id"] in {e["event_id"] for e in
                                 client.get(f"/api/matches/{MATCH}/events?raw=true").json()["events"]})

    print("\nStats, export, retry, media")
    s = client.get("/api/teams/254/stats").json()
    check("GET team stats has the contract fields",
          all(k in s for k in ("cycles", "avg_cycle_seconds", "shot_accuracy",
                               "avg_shot_interval_seconds", "low_confidence_events")),
          str(sorted(s))[:140])
    check("cycle time computed", s["avg_cycle_seconds"] is not None)

    r = client.post("/api/export/sheets", json={"match_ids": [MATCH], "mode": "aggregate"})
    check("export returns a URL and rows_skipped",
          "spreadsheet_url" in r.json() and "rows_skipped" in r.json())

    r = client.post(f"/api/jobs/{failed_job['job_id']}/retry")
    check("POST retry reuses the job id", r.json()["job_id"] == failed_job["job_id"])
    check("retry increments attempt", r.json()["attempt"] == failed_job["attempt"] + 1,
          str(r.json()["attempt"]))
    check("retry clears error_code", r.json()["error_code"] is None)

    r = client.get(f"/api/video/{main_job['job_id']}")
    check("GET /api/video/:job_id", r.status_code == 200, str(r.status_code))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
