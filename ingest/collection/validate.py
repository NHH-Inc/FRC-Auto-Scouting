"""Integrity validation for extracted collections and model proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .provenance import sha256_file


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def validate_collection(path: str | Path, *, verify_hashes: bool = True) -> dict[str, Any]:
    collection = Path(path)
    errors = []
    summary_path, frames_path = collection / "collection.json", collection / "frames.jsonl"
    if not summary_path.is_file():
        errors.append("missing collection.json")
    if not frames_path.is_file():
        errors.append("missing frames.jsonl")
    if errors:
        return {"valid": False, "errors": errors, "frame_count": 0}
    summary = json.loads(summary_path.read_text())
    frames = _rows(frames_path)
    ids: set[str] = set()
    for row in frames:
        frame_id = row.get("frame_id")
        if frame_id in ids:
            errors.append(f"duplicate frame ID: {frame_id}")
        ids.add(frame_id)
        image = collection / row.get("image_path", "")
        if not image.is_file():
            errors.append(f"missing image for {frame_id}: {image}")
        elif verify_hashes and sha256_file(image) != row.get("image_sha256"):
            errors.append(f"hash mismatch for {frame_id}")
    if summary.get("frame_count") != len(frames):
        errors.append("collection.json frame_count does not match frames.jsonl")
    proposal_count = 0
    proposals = collection / "model-proposals.jsonl"
    if proposals.exists():
        for row in _rows(proposals):
            proposal_count += 1
            if row.get("frame_id") not in ids:
                errors.append(f"orphan model proposal: {row.get('frame_id')}")
            if row.get("status") != "proposed" or row.get("human_review_required") is not True:
                errors.append(f"model result is not marked for review: {row.get('frame_id')}")
    sam3_proposal_count = 0
    sam3_proposals = collection / "sam3-proposals.jsonl"
    if sam3_proposals.exists():
        for row in _rows(sam3_proposals):
            sam3_proposal_count += 1
            if row.get("frame_id") not in ids:
                errors.append(f"orphan SAM 3 proposal: {row.get('frame_id')}")
            if row.get("status") != "proposed" or row.get("human_review_required") is not True:
                errors.append(f"SAM 3 result is not marked for review: {row.get('frame_id')}")
    return {
        "valid": not errors,
        "errors": errors,
        "frame_count": len(frames),
        "model_proposal_records": proposal_count,
        "sam3_proposal_records": sam3_proposal_count,
    }
