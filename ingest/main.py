"""Component 2's HTTP API -- Contract E.

Component 3 talks to this and nothing else, so every endpoint doc 0 lists exists here even
when the implementation behind it is thin. A missing endpoint is indistinguishable from a
broken one at the browser.
"""

import json
import os
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import database, downloader, models, orchestrator, stats
from .corrections import apply_corrections
from .serializers import (
    JOB_STATUSES,
    correction_to_dict,
    event_to_dict,
    job_to_dict,
    track_to_dict,
    validate_event_fields,
)

app = FastAPI(title="FRC Auto-Scouting Ingest Service")

# The web dev server runs on 5173 (doc 0 default). Vite proxies /api in dev, but a build
# served from anywhere else talks to this directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

database.init_db()

get_db = database.get_db

video_downloader = downloader.VideoDownloader(download_dir="./data/segments")
analysis_orchestrator = orchestrator.AnalysisOrchestrator(
    binary_path=os.environ.get("ANALYSIS_BINARY", "./analysis/build/bin/analysis")
)


# ---------------------------------------------------------------- jobs


@app.post("/api/jobs")
async def create_job(
    payload: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    url = payload.get("url")
    # match_id is optional per Contract E. Absent means "resolve it for me".
    match_id = payload.get("match_id")

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        info = video_downloader.get_video_info(url)
        video_id = info.get("id")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to get video info: {exc}")

    if not video_id:
        raise HTTPException(status_code=400, detail="Could not resolve a YouTube video ID")

    job_id = str(uuid.uuid4())
    db_job = models.Job(
        job_id=job_id,
        video_id=video_id,
        # Stays NULL when unresolved. Contract E: "returns the job with match_id: null if it
        # cannot". The string "unknown" is not a valid TBA key and would collide across every
        # unresolved job's events.
        match_id=match_id,
        status="queued",
        duration=info.get("duration"),
        fps=info.get("fps"),
        width=info.get("width"),
        height=info.get("height"),
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    background_tasks.add_task(process_job, job_id, url)

    return job_to_dict(db_job)


@app.get("/api/jobs")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(models.Job).order_by(models.Job.created_at.desc()).all()
    return [job_to_dict(job) for job in jobs]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_to_dict(job)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Events and tracks are the product; the downloaded media is a cache (doc 2). Deleting a
    # job removes its rows, and the segment file with them.
    db.query(models.Event).filter(models.Event.job_id == job_id).delete()
    db.query(models.Track).filter(models.Track.job_id == job_id).delete()
    if job.local_path and os.path.exists(job.local_path):
        try:
            os.remove(job.local_path)
        except OSError:
            pass
    db.delete(job)
    db.commit()
    return None


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(
    job_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Doc 3: retry "does not require re-pasting the link" -- the video_id is already here.

    Not in Contract E (see contracts/OPEN_QUESTIONS.md #5). Reusing the same job_id keeps the
    failure history attached instead of orphaning it behind a fresh UUID.
    """
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = "queued"
    job.error = None
    job.progress = None
    job.stage = None
    db.commit()
    db.refresh(job)
    background_tasks.add_task(
        process_job, job_id, f"https://www.youtube.com/watch?v={job.video_id}"
    )
    return job_to_dict(job)


def process_job(job_id: str, url: str):
    db = next(database.get_db())
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if job is None:
        return

    def set_status(status: str, **fields):
        job.status = status
        for key, value in fields.items():
            setattr(job, key, value)
        db.commit()

    try:
        set_status("downloading", stage="yt-dlp", progress=None)

        info = video_downloader.get_video_info(url)
        # TODO: derive the match window from TBA or the description chapter list. Until then
        # the segment is the whole video, so start_offset stays 0 and remains correct.
        start_offset = job.start_offset or 0.0
        duration = info.get("duration") or 150.0

        local_path = video_downloader.download_segment(
            video_id=job.video_id,
            start_time=start_offset,
            duration=duration,
            job_id=job_id,
        )

        # Write the media metadata back to the JOB, not just into the dict handed to the
        # binary. Component 3 sizes the player from these and cannot open one without them.
        set_status(
            "downloaded",
            local_path=local_path,
            duration=duration,
            fps=info.get("fps") or 30.0,
            width=info.get("width") or 1920,
            height=info.get("height") or 1080,
            stage=None,
        )

        set_status("analyzing", stage="starting", progress=0.0)

        job_data = job_to_dict(job)
        job_data.pop("error", None)
        job_data.pop("progress", None)
        job_data.pop("stage", None)
        job_data.pop("created_at", None)

        def on_progress(progress, stage):
            # Contract D streams this so a progress bar can exist; component 3 draws it, so
            # it has to reach the job record. See OPEN_QUESTIONS.md #4.
            job.progress = progress
            job.stage = stage
            db.commit()

        results = analysis_orchestrator.run_job(job_data, on_progress=on_progress)
        import_results(db, job, results)
        set_status("complete", progress=1.0, stage=None, error=None)

    except Exception as exc:
        # Doc 2: "treat a failed download as an expected condition, not a crash." Keep the
        # reason -- a retry the user cannot reason about is not much of a retry path.
        set_status("failed", error=str(exc)[:1000], progress=None, stage=None)
    finally:
        db.close()


def import_results(db: Session, job, results: dict):
    """Load events.jsonl and tracks.jsonl into the database."""
    with open(results["events_path"], "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            exists = (
                db.query(models.Event)
                .filter(models.Event.event_id == data["event_id"])
                .first()
            )
            if exists:
                continue
            db.add(
                models.Event(
                    event_id=data["event_id"],
                    schema_version=data.get("schema_version", 1),
                    job_id=data.get("job_id", job.job_id),
                    match_id=data.get("match_id", job.match_id),
                    team=data.get("team"),
                    track_id=data.get("track_id"),
                    t_seconds=data["t_seconds"],
                    phase=data["phase"],
                    event_type=data["event_type"],
                    confidence=data["confidence"],
                    field_x=data.get("field_x"),
                    field_y=data.get("field_y"),
                    source=data.get("source", "model"),
                )
            )

    with open(results["tracks_path"], "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            db.add(
                models.Track(
                    job_id=job.job_id,
                    # Contract C has NO match_id field. Reading it off the track JSON yields
                    # NULL for every row, and the tracks endpoint then returns nothing
                    # forever. It has to come from the job.
                    match_id=job.match_id,
                    track_id=data["track_id"],
                    team=data.get("team"),
                    alliance=data.get("alliance"),
                    boxes=data.get("boxes") or [],
                )
            )
    db.commit()


# ---------------------------------------------------------------- match data


def _events_for(db: Session, match_id: str, min_confidence: float, raw: bool) -> list[dict]:
    rows = (
        db.query(models.Event)
        .filter(models.Event.match_id == match_id)
        .order_by(models.Event.t_seconds)
        .all()
    )
    if raw:
        # Uncorrected model output: what the accuracy comparison and training export need.
        events = [event_to_dict(e) for e in rows]
    else:
        corrections = (
            db.query(models.Correction)
            .filter(models.Correction.match_id == match_id)
            .all()
        )
        events = apply_corrections(rows, corrections)
    return [e for e in events if (e.get("confidence") or 0.0) >= min_confidence]


@app.get("/api/matches/{match_id}/events")
def get_match_events(
    match_id: str,
    min_confidence: float = 0.0,
    raw: bool = Query(False, description="Return uncorrected model output."),
    db: Session = Depends(get_db),
):
    return _events_for(db, match_id, min_confidence, raw)


@app.get("/api/matches/{match_id}/tracks")
def get_match_tracks(match_id: str, db: Session = Depends(get_db)):
    rows = db.query(models.Track).filter(models.Track.match_id == match_id).all()
    return [track_to_dict(t) for t in rows]


@app.get("/api/matches/{match_id}/corrections")
def get_match_corrections(match_id: str, db: Session = Depends(get_db)):
    """Not in Contract E -- see OPEN_QUESTIONS.md #3.

    Without it a client has to fetch raw and corrected and diff them to find out which rows a
    human touched, which costs an extra request and still loses created_at.
    """
    rows = (
        db.query(models.Correction)
        .filter(models.Correction.match_id == match_id)
        .order_by(models.Correction.created_at)
        .all()
    )
    return [correction_to_dict(c) for c in rows]


@app.get("/api/matches/{match_id}/accuracy")
def get_match_accuracy(match_id: str, db: Session = Depends(get_db)):
    """Doc 1: "If the pipeline's reconstructed score does not match TBA's official score for
    the same match, the pipeline is wrong. That comparison is the main evaluation loop."

    Scored from RAW events on purpose. Using the corrected stream would measure the reviewers
    and the number would improve every time somebody fixed a row by hand.
    """
    job = db.query(models.Job).filter(models.Job.match_id == match_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="No job for that match")

    events = _events_for(db, match_id, 0.0, raw=True)
    reconstructed = stats.reconstruct_score(events, job.alliances)
    tba = job.tba_score
    delta = (
        {"red": reconstructed["red"] - tba["red"], "blue": reconstructed["blue"] - tba["blue"]}
        if tba
        else None
    )
    return {
        "match_id": match_id,
        "reconstructed": reconstructed,
        "tba": tba,
        "delta": delta,
    }


# ---------------------------------------------------------------- corrections


@app.post("/api/events")
def create_manual_event(event_data: dict, db: Session = Depends(get_db)):
    """Contract E: create a manual event. Recorded as a 'create' correction, not as raw output.

    The events table holds model output only, so a human-authored event lives in the
    corrections layer and is composed in on read.
    """
    payload = {k: v for k, v in event_data.items() if k not in ("event_id", "schema_version")}
    payload["source"] = "manual"

    match_id = payload.get("match_id")
    if not match_id:
        raise HTTPException(status_code=400, detail="match_id is required")

    checkable = {k: v for k, v in payload.items() if k not in ("job_id", "match_id")}
    problems = validate_event_fields(checkable)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))

    event_id = f"manual-{uuid.uuid4().hex[:12]}"
    fields = {**payload, "event_id": event_id, "schema_version": 1}

    db.add(
        models.Correction(
            event_id=event_id,
            match_id=match_id,
            action="create",
            fields=fields,
        )
    )
    db.commit()
    return fields


@app.patch("/api/events/{event_id}")
def update_event(event_id: str, updates: dict, db: Session = Depends(get_db)):
    """Records a correction. Does NOT modify the event row.

    Doc 0: "Corrections never overwrite model output... Keeping both is the whole point:
    overwriting destroys the ability to measure whether the model is improving." Mutating the
    row here would permanently destroy the model's original prediction -- it is not
    recoverable from the corrections table, which stores the new value, not the old one.
    """
    event = db.query(models.Event).filter(models.Event.event_id == event_id).first()

    # The target may be a manually created event, which lives only in the corrections layer.
    origin = (
        db.query(models.Correction)
        .filter(models.Correction.event_id == event_id)
        .first()
    )
    if not event and not origin:
        raise HTTPException(status_code=404, detail="Event not found")

    problems = validate_event_fields(updates)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))

    match_id = event.match_id if event else (origin.match_id if origin else None)
    db.add(
        models.Correction(
            event_id=event_id,
            match_id=match_id,
            action="edit",
            fields=updates,
        )
    )
    db.commit()

    corrected = _events_for(db, match_id, 0.0, raw=False) if match_id else []
    for row in corrected:
        if row.get("event_id") == event_id:
            return row
    raise HTTPException(status_code=404, detail="Event not found after correction")


@app.delete("/api/events/{event_id}", status_code=204)
def delete_event(event_id: str, db: Session = Depends(get_db)):
    """A delete is a correction too. The raw event stays in the table for evaluation."""
    event = db.query(models.Event).filter(models.Event.event_id == event_id).first()
    origin = (
        db.query(models.Correction)
        .filter(models.Correction.event_id == event_id)
        .first()
    )
    if not event and not origin:
        raise HTTPException(status_code=404, detail="Event not found")

    db.add(
        models.Correction(
            event_id=event_id,
            match_id=event.match_id if event else origin.match_id,
            action="delete",
            fields=None,
        )
    )
    db.commit()
    return None


# ---------------------------------------------------------------- stats and export


@app.get("/api/teams/{team}/stats")
def get_team_stats(team: int, event_key: str | None = None, db: Session = Depends(get_db)):
    """Aggregates, computed per request. Doc 0: never stored, only queried."""
    jobs_query = db.query(models.Job).filter(models.Job.match_id.isnot(None))
    if event_key:
        jobs_query = jobs_query.filter(models.Job.match_id.like(f"{event_key}_%"))
    match_ids = [job.match_id for job in jobs_query.all()]

    events: list[dict] = []
    played = 0
    for match_id in match_ids:
        rows = _events_for(db, match_id, 0.0, raw=False)
        if any(e.get("team") == team for e in rows):
            played += 1
        events.extend(rows)

    return stats.team_stats(team, events, event_key, played)


@app.post("/api/export/sheets")
def export_to_sheets(payload: dict, db: Session = Depends(get_db)):
    """Doc 3: "Sheets is an export destination, not storage."

    Still a stub for the Google API call itself, but it now returns the shape component 3
    consumes -- crucially a spreadsheet URL, without which the UI cannot link the user to
    what it just wrote. See OPEN_QUESTIONS.md #6.
    """
    match_ids = payload.get("match_ids", [])
    mode = payload.get("mode", "aggregate")
    if mode not in ("raw", "aggregate"):
        raise HTTPException(status_code=400, detail="mode must be 'raw' or 'aggregate'")

    rows = 0
    for match_id in match_ids:
        events = _events_for(db, match_id, 0.0, raw=False)
        if mode == "raw":
            rows += len(events)
        else:
            rows += len({e.get("team") for e in events if e.get("team") is not None})

    spreadsheet_id = os.environ.get("SHEETS_SPREADSHEET_ID", "")
    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_url": (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
            if spreadsheet_id
            else ""
        ),
        "rows_written": rows,
        "rows_updated": 0,
        "mode": mode,
    }


# ---------------------------------------------------------------- media


@app.get("/api/video/{job_id}")
def get_video(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job or not job.local_path or not os.path.exists(job.local_path):
        raise HTTPException(status_code=404, detail="Video file not found")
    # FileResponse answers HTTP range requests, which <video> needs in order to seek.
    return FileResponse(job.local_path, media_type="video/mp4")


@app.get("/api/health")
def health():
    return {"status": "ok", "schema_version": 1, "statuses": sorted(JOB_STATUSES)}
