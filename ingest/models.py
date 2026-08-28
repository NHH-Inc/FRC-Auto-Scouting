from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, JSON, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
import datetime
import uuid

Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    schema_version = Column(Integer, default=1)
    match_id = Column(String, nullable=True)
    video_id = Column(String(11), nullable=False)
    local_path = Column(String, nullable=True)
    start_offset = Column(Float, default=0.0)
    duration = Column(Float, nullable=True)
    fps = Column(Float, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    status = Column(String, default="queued") # queued, downloading, downloaded, analyzing, complete, failed
    alliances = Column(JSON, nullable=True)
    tba_score = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Event(Base):
    __tablename__ = "events"
    event_id = Column(String, primary_key=True)
    schema_version = Column(Integer, default=1)
    job_id = Column(String, ForeignKey("jobs.job_id"))
    match_id = Column(String, index=True)
    team = Column(Integer, nullable=True)
    track_id = Column(Integer)
    t_seconds = Column(Float)
    phase = Column(String) # auto, teleop, endgame, unknown
    event_type = Column(String)
    confidence = Column(Float)
    field_x = Column(Float, nullable=True)
    field_y = Column(Float, nullable=True)
    source = Column(String) # model, scoreboard_ocr, tba, manual
    raw = Column(Boolean, default=True)

class Track(Base):
    __tablename__ = "tracks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.job_id"))
    match_id = Column(String, index=True)
    track_id = Column(Integer)
    team = Column(Integer, nullable=True)
    alliance = Column(String) # red, blue
    boxes = Column(JSON) # List of boxes

class Correction(Base):
    __tablename__ = "corrections"
    correction_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id = Column(String, ForeignKey("events.event_id"))
    action = Column(String) # edit, delete, create
    fields = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
