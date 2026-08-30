"""Materialise consensus labels into RF-DETR's COCO directory layout.

The collection manifest remains the durable record (video/frame references plus boxes). This
module creates a disposable local copy of the images because RF-DETR expects each split to hold
its JPEGs beside ``_annotations.coco.json``.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CollectionConfig


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _copy_or_link(source: Path, destination: Path) -> None:
    """Hard-link locally when possible; fall back to a disposable copy on Windows volumes."""
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _coco_payload(*, split: str, categories: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "info": {
            "description": "FRC robot detector dataset",
            "version": "1.0",
            "split": split,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "licenses": [],
        "images": [],
        "annotations": [],
        "categories": categories,
    }


def export_coco_dataset(
    *,
    collection: str | Path | list[str | Path],
    config: CollectionConfig,
    output: str | Path,
    allow_unreviewed: bool,
    labels_file: str = "model-consensus.jsonl",
) -> dict[str, Any]:
    """Build a COCO dataset consumable by ``RFDETR*.train(dataset_dir=...)``.

    Unreviewed VLM consensus is accepted only when requested explicitly. That implements the
    team's temporary v1 decision without making auto-labels look like human ground truth.
    """
    collection_paths = [Path(item) for item in collection] if isinstance(collection, list) else [Path(collection)]
    if not collection_paths:
        raise ValueError("At least one collection is required")
    output_path = Path(output)
    if output_path.exists() and any(output_path.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty dataset directory: {output_path}")
    frames: dict[str, tuple[dict[str, Any], Path]] = {}
    label_rows: list[tuple[dict[str, Any], Path]] = []
    for collection_path in collection_paths:
        for frame in _read_jsonl(collection_path / "frames.jsonl"):
            frame_id = str(frame["frame_id"])
            if frame_id in frames:
                raise ValueError(f"Duplicate frame_id across collections: {frame_id}")
            frames[frame_id] = (frame, collection_path)
        label_rows.extend((row, collection_path) for row in _read_jsonl(collection_path / labels_file))
    if not frames:
        raise ValueError("Collection contains no frames")
    if not label_rows:
        raise ValueError(f"Collection contains no labels in {labels_file}")

    categories = [
        {
            "id": int(item.get("id", index)),
            "name": str(item["name"]),
            "supercategory": "none",
        }
        for index, item in enumerate(config.raw["classes"])
    ]
    category_ids = {item["name"]: item["id"] for item in categories}
    split_names = {"train": "train", "val": "valid", "test": "test"}
    payloads = {name: _coco_payload(split=name, categories=categories) for name in split_names.values()}
    next_image_id = 1
    next_annotation_id = 1
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"images": 0, "annotations": 0})

    output_path.mkdir(parents=True, exist_ok=True)
    for split in split_names.values():
        (output_path / split).mkdir(exist_ok=True)

    for label_row, collection_path in sorted(label_rows, key=lambda item: item[0]["frame_id"]):
        frame_entry = frames.get(label_row["frame_id"])
        if frame_entry is None:
            raise ValueError(f"Label references unknown frame: {label_row['frame_id']}")
        frame, frame_collection_path = frame_entry
        if frame_collection_path != collection_path:
            raise ValueError(f"Label belongs to the wrong collection: {label_row['frame_id']}")
        status = str(label_row.get("review_status", label_row.get("status", "unreviewed")))
        if status not in {"reviewed", "accepted", "approved"} and not allow_unreviewed:
            raise ValueError(
                "Refusing unreviewed proposals. Review them in Roboflow first, or pass "
                "--allow-unreviewed for the explicitly temporary v1 baseline."
            )
        split = split_names.get(str(frame["split"]))
        if split is None:
            raise ValueError(f"Frame has an invalid split: {frame['split']}")
        source = collection_path / frame["image_path"]
        if not source.is_file():
            raise FileNotFoundError(f"Frame image is missing: {source}")
        filename = f"{frame['frame_id']}{source.suffix.lower() or '.jpg'}"
        _copy_or_link(source, output_path / split / filename)
        payload = payloads[split]
        image_id = next_image_id
        next_image_id += 1
        width_px, height_px = int(frame["width"]), int(frame["height"])
        payload["images"].append({"id": image_id, "file_name": filename, "width": width_px, "height": height_px})
        counts[split]["images"] += 1
        for box in label_row.get("boxes", []):
            class_name = str(box.get("class_name", ""))
            if class_name not in category_ids:
                raise ValueError(f"Unknown class in {frame['frame_id']}: {class_name}")
            raw_x, raw_y = float(box["x"]), float(box["y"])
            left, top = max(0.0, raw_x), max(0.0, raw_y)
            right, bottom = min(1.0, raw_x + float(box["w"])), min(1.0, raw_y + float(box["h"]))
            x, y = left * width_px, top * height_px
            box_width, box_height = (right - left) * width_px, (bottom - top) * height_px
            if box_width <= 0.0 or box_height <= 0.0:
                continue
            payload["annotations"].append({
                "id": next_annotation_id, "image_id": image_id, "category_id": category_ids[class_name],
                "bbox": [round(x, 3), round(y, 3), round(box_width, 3), round(box_height, 3)],
                "area": round(box_width * box_height, 3), "iscrowd": 0,
            })
            next_annotation_id += 1
            counts[split]["annotations"] += 1

    for split, payload in payloads.items():
        (output_path / split / "_annotations.coco.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    summary = {
        "format": "coco", "collections": [str(path) for path in collection_paths], "labels_file": labels_file,
        "allow_unreviewed": allow_unreviewed, "classes": categories, "splits": dict(counts),
        "warning": "This is materialized training input, not the label system of record. Delete and regenerate it after labels change.",
    }
    (output_path / "dataset.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
