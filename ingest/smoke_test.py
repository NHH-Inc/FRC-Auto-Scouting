"""Contract E smoke test.

Seeds the golden fixture straight into the database and drives every endpoint component 3
calls. No network, no yt-dlp, no analysis binary -- doc 0: "Component 2 tests the pipeline
with a stub binary that copies the fixture output."

Run from the repo root:

    ingest/.venv/Scripts/python -m ingest.smoke_test        (Windows)
    ingest/.venv/bin/python -m ingest.smoke_test            (POSIX)
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "2026casf_qm42"

# Must be set before ingest.database is imported -- the engine is built at import time.
_tmp_db = Path(tempfile.mkdtemp()) / "smoke.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402

from ingest import database, models  # noqa: E402
from ingest.main import app  # noqa: E402

MATCH = "2026casf_qm42"

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
    dest = _tmp_db.parent / "segment.mp4"
    src = FIXTURE / "segment.mp4"
    if src.exists():
        shutil.copy2(src, dest)
    else:
        dest.write_bytes(b"")
    return dest


def seed():
    db = database.SessionLocal()
    job_data = json.loads((FIXTURE / "job.json").read_text(encoding="utf-8"))
    job = models.Job(
        job_id=job_data["job_id"],
        match_id=job_data["match_id"],
        video_id=job_data["video_id"],
        # A COPY: deleting a job removes its cached segment (doc 2: media is a cache,
        # not a record), and pointing this at the fixture would delete the golden video.
        local_path=str(_segment_copy()),
        start_offset=job_data["start_offset"],
        duration=job_data["duration"],
        fps=job_data["fps"],
        width=job_data["width"],
        height=job_data["height"],
        status="complete",
        alliances=job_data["alliances"],
        tba_score=job_data["tba_score"],
    )
    db.add(job)
    for row in jsonl(FIXTURE / "events.jsonl"):
        db.add(
            models.Event(
                event_id=row["event_id"], schema_version=row["schema_version"],
                job_id=row["job_id"], match_id=row["match_id"], team=row["team"],
                track_id=row["track_id"], t_seconds=row["t_seconds"], phase=row["phase"],
                event_type=row["event_type"], confidence=row["confidence"],
                field_x=row["field_x"], field_y=row["field_y"], source=row["source"],
            )
        )
    for row in jsonl(FIXTURE / "tracks.jsonl"):
        db.add(
            models.Track(
                job_id=job_data["job_id"],
                match_id=job_data["match_id"],  # from the JOB, never the track JSON
                track_id=row["track_id"], team=row["team"],
                alliance=row["alliance"], boxes=row["boxes"],
            )
        )
    db.commit()
    db.close()


def main():
    seed()
    client = TestClient(app)
    raw_count = len(jsonl(FIXTURE / "events.jsonl"))

    print("\nContract E endpoints")
    r = client.get("/api/jobs")
    check("GET /api/jobs", r.status_code == 200 and len(r.json()) == 1, str(r.status_code))
    job = r.json()[0]
    check("job carries media metadata", job["duration"] and job["fps"] and job["width"])
    check("job has schema_version", job.get("schema_version") == 1)

    r = client.get(f"/api/jobs/{job['job_id']}")
    check("GET /api/jobs/:id", r.status_code == 200)

    r = client.get(f"/api/matches/{MATCH}/events")
    check("GET events", r.status_code == 200 and len(r.json()) == raw_count)
    check("event has all 13 contract fields", len(r.json()[0]) == 13, str(sorted(r.json()[0])))

    r = client.get(f"/api/matches/{MATCH}/events?min_confidence=0.8")
    check("min_confidence filters", all(e["confidence"] >= 0.8 for e in r.json()))

    # The bug that made the overlay impossible: tracks stored with a match_id read off the
    # track JSON, which Contract C does not have, so this returned [] forever.
    r = client.get(f"/api/matches/{MATCH}/tracks")
    tracks = r.json()
    check("GET tracks returns the tracks", len(tracks) == 7, f"got {len(tracks)}")
    check("track has no match_id leak", "match_id" not in (tracks[0] if tracks else {}))
    check("track has boxes", bool(tracks and tracks[0]["boxes"]))

    r = client.get(f"/api/matches/{MATCH}/accuracy")
    acc = r.json()
    check("GET accuracy", r.status_code == 200 and "reconstructed" in acc, str(acc)[:120])
    check("accuracy has a delta vs TBA", acc.get("delta") is not None)

    print("\nCorrections never overwrite raw output")
    target = client.get(f"/api/matches/{MATCH}/events").json()[1]
    original_team = target["team"]
    new_team = 1678 if original_team != 1678 else 254

    r = client.patch(f"/api/events/{target['event_id']}", json={"team": new_team})
    check("PATCH event", r.status_code == 200 and r.json()["team"] == new_team, str(r.status_code))

    r = client.get(f"/api/matches/{MATCH}/events?raw=true")
    raw_rows = {e["event_id"]: e for e in r.json()}
    check(
        "?raw=true still reports the ORIGINAL team",
        raw_rows[target["event_id"]]["team"] == original_team,
        f"raw now says {raw_rows[target['event_id']]['team']}, expected {original_team}",
    )

    r = client.get(f"/api/matches/{MATCH}/events")
    corrected = {e["event_id"]: e for e in r.json()}
    check("corrected view shows the new team", corrected[target["event_id"]]["team"] == new_team)

    r = client.get(f"/api/matches/{MATCH}/corrections")
    check("GET corrections lists it", r.status_code == 200 and len(r.json()) == 1)

    print("\nManual events and deletes")
    r = client.post(
        "/api/events",
        json={
            "job_id": job["job_id"], "match_id": MATCH, "team": 254, "track_id": 7,
            "t_seconds": 63.5, "phase": "teleop", "event_type": "shot_made",
            "confidence": 1.0, "field_x": None, "field_y": None, "source": "manual",
        },
    )
    check("POST /api/events (was a TypeError)", r.status_code == 200, r.text[:160])

    r = client.get(f"/api/matches/{MATCH}/events")
    check("manual event appears in the corrected view", len(r.json()) == raw_count + 1)
    r = client.get(f"/api/matches/{MATCH}/events?raw=true")
    check("manual event is NOT in raw output", len(r.json()) == raw_count)

    r = client.post("/api/events", json={"match_id": MATCH, "phase": "halftime"})
    check("unknown enum value is rejected", r.status_code == 400, str(r.status_code))

    r = client.delete(f"/api/events/{target['event_id']}")
    check("DELETE /api/events/:id", r.status_code == 204, str(r.status_code))
    r = client.get(f"/api/matches/{MATCH}/events")
    check("deleted event is gone from the view", target["event_id"] not in {e["event_id"] for e in r.json()})
    r = client.get(f"/api/matches/{MATCH}/events?raw=true")
    check("deleted event survives in raw", target["event_id"] in {e["event_id"] for e in r.json()})

    print("\nStats and export")
    r = client.get("/api/teams/254/stats")
    s = r.json()
    check("GET team stats", r.status_code == 200 and s["team"] == 254, str(r.status_code))
    check("cycle time computed", s["median_cycle_seconds"] is not None, str(s)[:140])

    r = client.post("/api/export/sheets", json={"match_ids": [MATCH], "mode": "aggregate"})
    check("POST export/sheets", r.status_code == 200 and "spreadsheet_url" in r.json())
    r = client.post("/api/export/sheets", json={"match_ids": [MATCH], "mode": "sideways"})
    check("bad export mode rejected", r.status_code == 400)

    print("\nMedia and job lifecycle")
    r = client.get(f"/api/video/{job['job_id']}")
    check("GET /api/video/:job_id", r.status_code == 200, str(r.status_code))

    r = client.delete(f"/api/jobs/{job['job_id']}")
    check("DELETE /api/jobs/:id", r.status_code == 204, str(r.status_code))
    check("job is gone", client.get(f"/api/jobs/{job['job_id']}").status_code == 404)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
