"""Deterministic MP4-to-frame extraction and manifest creation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import COLLECTION_SCHEMA_VERSION, EXTRACTOR_VERSION
from .config import CollectionConfig
from .provenance import probe_video, sha256_file


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _split_for(group: str, config: CollectionConfig) -> str:
    split = config.raw["split"]
    seed = str(split["seed"])
    value = int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:16], 16) / 2**64
    train = float(split["train"])
    val = float(split["val"])
    return "train" if value < train else "val" if value < train + val else "test"


def extract_collection(
    *,
    segment: str | Path,
    match_id: str,
    video_id: str,
    source_url: str,
    start_offset: float,
    config: CollectionConfig,
    collection_id: str | None = None,
    job_id: str | None = None,
) -> Path:
    segment_path = Path(segment).resolve()
    metadata = probe_video(segment_path)
    segment_hash = sha256_file(segment_path)
    identity = hashlib.sha256(
        f"{segment_hash}:{config.digest}:{match_id}:{video_id}:{start_offset}".encode()
    ).hexdigest()[:8]
    collection_id = collection_id or f"{config.season}-frc-robot-{match_id}-{identity}"
    collection_path = config.collections_root / collection_id
    summary_path = collection_path / "collection.json"
    if summary_path.exists():
        current = json.loads(summary_path.read_text())
        if current.get("segment_sha256") == segment_hash and current.get("config_sha256") == config.digest:
            return collection_path
        raise FileExistsError(
            f"{collection_path} already exists with different source/config; choose a new collection ID"
        )
    config.collections_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{collection_id}-", dir=config.collections_root))
    try:
        frames_dir = temporary / "frames" / match_id
        frames_dir.mkdir(parents=True)
        output_pattern = frames_dir / "f%06d.jpg"
        qscale = max(2, min(31, round((100 - config.jpeg_quality) * 29 / 99 + 2)))
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(segment_path),
            "-vf", f"fps={config.sampling_fps}:round=near:start_time=0",
            "-q:v", str(qscale), "-start_number", "0", str(output_pattern),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("ffmpeg is required for frame extraction") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"ffmpeg extraction failed: {exc.stderr.strip()}") from exc
        images = sorted(frames_dir.glob("f*.jpg"))
        if not images:
            raise RuntimeError("ffmpeg produced no frames")
        split = _split_for(match_id or f"{video_id}:{start_offset}", config)
        rows = []
        for number, image in enumerate(images):
            segment_time = number / config.sampling_fps
            rows.append({
                "frame_id": f"{collection_id}-f{number:06d}",
                "collection_id": collection_id,
                "match_id": match_id,
                "video_id": video_id,
                "segment_time_seconds": round(segment_time, 6),
                "source_video_time_seconds": round(start_offset + segment_time, 6),
                "frame_index": round(segment_time * metadata["fps"]),
                "image_path": str(image.relative_to(temporary)),
                "image_sha256": sha256_file(image),
                "width": metadata["width"],
                "height": metadata["height"],
                "review_status": "unreviewed",
                "split": split,
            })
        created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        summary = {
            "collection_id": collection_id,
            "collection_schema_version": COLLECTION_SCHEMA_VERSION,
            "season": config.season,
            "game": config.game,
            "match_id": match_id,
            "job_id": job_id,
            "video_id": video_id,
            "source_url": source_url,
            "segment_path": str(segment_path),
            "segment_sha256": segment_hash,
            "config_sha256": config.digest,
            "start_offset_seconds": start_offset,
            "segment_duration_seconds": metadata["duration"],
            "fps": metadata["fps"],
            "width": metadata["width"],
            "height": metadata["height"],
            "sampling_fps": config.sampling_fps,
            "frame_count": len(rows),
            "extractor_version": EXTRACTOR_VERSION,
            "created_at": created,
        }
        _write_json(temporary / "collection.json", summary)
        _write_jsonl(temporary / "frames.jsonl", rows)
        _write_json(temporary / "config.snapshot.json", config.raw)
        temporary.rename(collection_path)
        return collection_path
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
