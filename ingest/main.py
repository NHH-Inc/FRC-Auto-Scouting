from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import uuid
import os
import json

from . import models, database, downloader, orchestrator

app = FastAPI(title="FRC Auto-Scouting Ingest Service")

# Initialize DB on startup
database.init_db()

# Dependency
get_db = database.get_db

video_downloader = downloader.VideoDownloader(download_dir="./data/segments")
analysis_orchestrator = orchestrator.AnalysisOrchestrator(binary_path="./analysis/build/bin/analysis")

@app.post("/api/jobs")
async def create_job(payload: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    url = payload.get("url")
    match_id = payload.get("match_id")

    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # 1. Get video info
    try:
        info = video_downloader.get_video_info(url)
        video_id = info.get("id")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to get video info: {str(e)}")

    # 2. Create job record
    job_id = str(uuid.uuid4())
    db_job = models.Job(
        job_id=job_id,
        video_id=video_id,
        match_id=match_id,
        status="queued"
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    # 3. Queue download and analysis
    background_tasks.add_task(process_job, job_id, url, match_id)

    return db_job

async def process_job(job_id: str, url: str, match_id: str):
    # This would update the DB status as it goes
    # Using a new session because it's a background task
    db = next(database.get_db())
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()

    try:
        job.status = "downloading"
        db.commit()

        info = video_downloader.get_video_info(url)
        # Simplified: download full match if no start/end provided
        # In real usage, we'd extract match window from TBA/Metadata
        local_path = video_downloader.download_segment(
            video_id=job.video_id,
            start_time=0.0,
            duration=info.get("duration", 150.0),
            job_id=job_id
        )

        job.local_path = local_path
        job.status = "downloaded"
        db.commit()

        # Start analysis
        job.status = "analyzing"
        db.commit()

        # Prepare job data for binary (Contract A)
        job_data = {
            "schema_version": 1,
            "job_id": job.job_id,
            "match_id": job.match_id or "unknown",
            "video_id": job.video_id,
            "local_path": job.local_path,
            "start_offset": job.start_offset,
            "duration": job.duration or info.get("duration"),
            "fps": job.fps or 30.0,
            "width": job.width or 1920,
            "height": job.height or 1080,
            "status": job.status,
            "alliances": job.alliances,
            "tba_score": job.tba_score
        }

        results = analysis_orchestrator.run_job(job_data)

        # Import events and tracks into DB
        import_results(db, job_id, results)

        job.status = "complete"
        db.commit()

    except Exception as e:
        job.status = "failed"
        # Log error...
        db.commit()

def import_results(db: Session, job_id: str, results: dict):
    # Read events.jsonl and tracks.jsonl and insert into DB
    with open(results["events_path"], "r") as f:
        for line in f:
            if not line.strip(): continue
            data = json.loads(line)
            # Ensure we don't have duplicate event_ids if re-running
            existing = db.query(models.Event).filter(models.Event.event_id == data["event_id"]).first()
            if not existing:
                event = models.Event(**data)
                db.add(event)

    with open(results["tracks_path"], "r") as f:
        for line in f:
            if not line.strip(): continue
            data = json.loads(line)
            track = models.Track(
                job_id=job_id,
                match_id=data.get("match_id"),
                track_id=data["track_id"],
                team=data.get("team"),
                alliance=data.get("alliance"),
                boxes=data["boxes"]
            )
            db.add(track)
    db.commit()

@app.get("/api/video/{job_id}")
def get_video(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job or not job.local_path or not os.path.exists(job.local_path):
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(job.local_path)

@app.post("/api/export/sheets")
def export_to_sheets(payload: dict, db: Session = Depends(get_db)):
    match_ids = payload.get("match_ids", [])
    mode = payload.get("mode", "aggregate")

    # Placeholder for Google Sheets API logic
    # This would involve:
    # 1. Fetching data from DB
    # 2. Formatting for Sheets
    # 3. Using Google API client to push data

    return {"message": "Export initiated", "match_count": len(match_ids)}

@app.get("/api/jobs")
def list_jobs(db: Session = Depends(get_db)):
    return db.query(models.Job).all()

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.get("/api/matches/{match_id}/events")
def get_match_events(match_id: str, min_confidence: float = 0.0, db: Session = Depends(get_db)):
    return db.query(models.Event).filter(
        models.Event.match_id == match_id,
        models.Event.confidence >= min_confidence
    ).all()

@app.get("/api/matches/{match_id}/tracks")
def get_match_tracks(match_id: str, db: Session = Depends(get_db)):
    return db.query(models.Track).filter(models.Track.match_id == match_id).all()

@app.post("/api/events")
def create_manual_event(event_data: dict, db: Session = Depends(get_db)):
    event_id = str(uuid.uuid4())
    db_event = models.Event(
        event_id=event_id,
        source="manual",
        **event_data
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@app.patch("/api/events/{event_id}")
def update_event(event_id: str, updates: dict, db: Session = Depends(get_db)):
    db_event = db.query(models.Event).filter(models.Event.event_id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Create correction record
    correction = models.Correction(
        event_id=event_id,
        action="edit",
        fields=updates
    )
    db.add(correction)

    # Apply updates to event (simplification for this example)
    for key, value in updates.items():
        setattr(db_event, key, value)

    db.commit()
    return db_event

