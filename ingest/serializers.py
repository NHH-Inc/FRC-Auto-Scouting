"""ORM rows -> the exact shapes in /contracts/.

Returning SQLAlchemy models straight out of FastAPI works, but the response shape then
silently tracks whatever the columns happen to be. These functions pin it to the contracts
instead, so a stray column cannot leak into a response and a missing one fails loudly here
rather than in the browser.

snake_case throughout, per doc 0. Component 3 converts to camelCase at its own boundary.
"""

import datetime

SCHEMA_VERSION = 1


def iso_z(dt: datetime.datetime | None) -> str | None:
    """ISO 8601, UTC, Z suffix -- doc 0's stated format for metadata timestamps."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def job_to_dict(job) -> dict:
    """Contract A."""
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job.job_id,
        "match_id": job.match_id,
        "video_id": job.video_id,
        "local_path": job.local_path,
        "start_offset": job.start_offset,
        "duration": job.duration,
        "fps": job.fps,
        "width": job.width,
        "height": job.height,
        "status": job.status,
        "alliances": job.alliances,
        "tba_score": job.tba_score,
        "error": job.error,
        "progress": job.progress,
        "stage": job.stage,
        "created_at": iso_z(job.created_at),
    }


def event_to_dict(event) -> dict:
    """Contract B. All thirteen fields, always -- consumers must not have to guess."""
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": event.job_id,
        "match_id": event.match_id,
        "event_id": event.event_id,
        "team": event.team,
        "track_id": event.track_id,
        "t_seconds": event.t_seconds,
        "phase": event.phase,
        "event_type": event.event_type,
        "confidence": event.confidence,
        "field_x": event.field_x,
        "field_y": event.field_y,
        "source": event.source,
    }


def track_to_dict(track) -> dict:
    """Contract C. No match_id: it is a storage detail, not part of the contract."""
    return {
        "schema_version": SCHEMA_VERSION,
        "track_id": track.track_id,
        "team": track.team,
        "alliance": track.alliance,
        "boxes": track.boxes or [],
    }


def correction_to_dict(correction) -> dict:
    return {
        "correction_id": correction.correction_id,
        "event_id": correction.event_id,
        "action": correction.action,
        "fields": correction.fields,
        "created_at": iso_z(correction.created_at),
    }


# Contract B field names, used to reject unknown keys in a correction patch.
EVENT_FIELDS = {
    "team",
    "track_id",
    "t_seconds",
    "phase",
    "event_type",
    "confidence",
    "field_x",
    "field_y",
    "source",
}

# Closed sets from /contracts/enums.md. Doc 0: "Anything unrecognized is a bug, not a
# fallback" -- so these are validated on the way in rather than stored and discovered later.
PHASES = {"auto", "teleop", "endgame", "unknown"}
EVENT_TYPES = {
    "match_start",
    "match_end",
    "phase_change",
    "shot_attempt",
    "shot_made",
    "reload",
    "defense_start",
    "defense_end",
    "immobile_start",
    "immobile_end",
    "foul",
}
SOURCES = {"model", "scoreboard_ocr", "tba", "manual"}
JOB_STATUSES = {
    "queued",
    "downloading",
    "downloaded",
    "analyzing",
    "complete",
    "failed",
}


def validate_event_fields(fields: dict) -> list[str]:
    """Returns a list of problems; empty means the patch is contract-legal."""
    problems = []
    for key, value in fields.items():
        if key not in EVENT_FIELDS:
            problems.append(f"'{key}' is not a correctable event field")
            continue
        if key == "phase" and value not in PHASES:
            problems.append(f"phase '{value}' is not one of {sorted(PHASES)}")
        if key == "event_type" and value not in EVENT_TYPES:
            problems.append(f"event_type '{value}' is not a known event type")
        if key == "source" and value not in SOURCES:
            problems.append(f"source '{value}' is not one of {sorted(SOURCES)}")
        if key == "confidence" and not (
            isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0
        ):
            problems.append("confidence must be a float 0..1, never a percentage")
        if key == "team" and value is not None and not isinstance(value, int):
            problems.append("team must be an integer with no 'frc' prefix, or null")
    return problems
