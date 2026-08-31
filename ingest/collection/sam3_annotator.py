"""Optional SAM 3.1 text-prompt proposals for FRC robot-label review.

SAM is deliberately an *additional* proposal source.  It does not replace the local Ollama
ensemble, human review, or the RF-DETR detector trained from reviewed boxes.  Its heavyweight
CUDA/PyTorch dependency is imported only when this command is invoked, keeping normal ingest
machines and tests free of SAM's requirements.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SAM3_ANNOTATOR_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
    )
    temporary.replace(path)


def _as_list(value: Any) -> list[Any]:
    """Convert a tensor/NumPy array/list without making either package a normal dependency."""
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "float"):
        value = value.float()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    return value if isinstance(value, list) else []


def normalise_xyxy_box(
    raw_box: list[float] | tuple[float, float, float, float],
    score: float,
    *,
    width: int,
    height: int,
    min_score: float,
) -> dict[str, Any] | None:
    """Translate SAM's image-space xyxy output to this repo's normalized xywh convention."""
    if len(raw_box) != 4 or width <= 0 or height <= 0 or not (0.0 <= score <= 1.0):
        return None
    try:
        left, top, right, bottom = (float(value) for value in raw_box)
    except (TypeError, ValueError):
        return None
    if score < min_score:
        return None
    left, right = max(0.0, min(left, width)), max(0.0, min(right, width))
    top, bottom = max(0.0, min(top, height)), max(0.0, min(bottom, height))
    if right <= left or bottom <= top:
        return None
    return {
        "class_name": "robot",
        "team": None,
        "x": round(left / width, 6),
        "y": round(top / height, 6),
        "w": round((right - left) / width, 6),
        "h": round((bottom - top) / height, 6),
        "confidence": round(score, 6),
        "source": "sam3.1_text",
    }


def _load_sam3():
    try:
        import torch
        from PIL import Image
        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model
    except ImportError as exc:
        raise RuntimeError(
            "SAM 3.1 is not installed in this Python environment. Follow docs/TRAINING.md on "
            "Robert's NVIDIA/CUDA machine; do not install it into ingest/.venv."
        ) from exc
    if not torch.cuda.is_available():
        raise RuntimeError("SAM 3.1 proposals require an NVIDIA CUDA GPU; CUDA was not detected")
    return torch, Image, build_sam3_image_model, Sam3Processor


def annotate_collection_sam3(
    *,
    collection: str | Path,
    prompt: str = "FRC competition robot",
    min_score: float = 0.35,
    limit: int | None = None,
    force: bool = False,
) -> Path:
    """Write independently reviewable text-prompt proposals for extracted collection frames."""
    if not 0.0 <= min_score <= 1.0:
        raise ValueError("min_score must be between 0 and 1")
    collection_path = Path(collection)
    frames = _read_jsonl(collection_path / "frames.jsonl")
    if not frames:
        raise ValueError(f"No frames.jsonl records found in {collection_path}")
    if limit is not None:
        frames = frames[:limit]

    torch, Image, build_model, processor_class = _load_sam3()
    model = build_model()
    processor = processor_class(model)
    output_path = collection_path / "sam3-proposals.jsonl"
    rows = _read_jsonl(output_path)
    requested_ids = {str(frame["frame_id"]) for frame in frames}
    if force:
        rows = [row for row in rows if str(row.get("frame_id")) not in requested_ids]
    existing = {str(row.get("frame_id")) for row in rows}

    for frame in frames:
        frame_id = str(frame["frame_id"])
        if frame_id in existing:
            continue
        image_path = collection_path / str(frame["image_path"])
        if not image_path.is_file():
            raise FileNotFoundError(f"Frame image is missing: {image_path}")
        image = Image.open(image_path).convert("RGB")
        # SAM's official examples expose image detection through set_image + set_text_prompt.
        # Ampere GPUs (including Robert's RTX 3060) support bfloat16 autocast.
        with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            state = processor.set_image(image)
            result = processor.set_text_prompt(state=state, prompt=prompt)
        raw_boxes, raw_scores = _as_list(result.get("boxes")), _as_list(result.get("scores"))
        boxes = [
            box
            for raw_box, raw_score in zip(raw_boxes, raw_scores)
            if (box := normalise_xyxy_box(
                raw_box, float(raw_score), width=int(frame["width"]), height=int(frame["height"]),
                min_score=min_score,
            )) is not None
        ]
        rows.append({
            "frame_id": frame_id,
            "model": "sam3.1",
            "annotator_version": SAM3_ANNOTATOR_VERSION,
            "generated_at": _utc_now(),
            "status": "proposed",
            "human_review_required": True,
            "prompt": prompt,
            "min_score": min_score,
            "box_format": "xyxy_absolute_pixels",
            "raw_box_count": len(raw_boxes),
            "boxes": boxes,
        })
        rows.sort(key=lambda row: str(row["frame_id"]))
        _write_jsonl(output_path, rows)
        print(f"{frame_id}: SAM 3.1 proposed {len(boxes)} robot boxes", flush=True)
    return output_path
