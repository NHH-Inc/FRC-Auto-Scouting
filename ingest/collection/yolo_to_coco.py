"""Convert a YOLO dataset to the COCO layout RF-DETR expects.

The two formats disagree about almost everything a box is:

    YOLO    class  centre-x  centre-y  width  height     all normalised 0-1
    COCO    top-left-x  top-left-y  width  height        all absolute pixels

So the conversion is not a reformat, it is a change of coordinate system, and getting it wrong
produces boxes that are the right shape in the wrong place -- which trains a model perfectly well
on the wrong answer. Image dimensions are read from each file rather than assumed, because a
dataset that has been resized by one tool and cropped by another will not have uniform sizes and
nothing will complain.

COCO category ids start at 1 in the official spec; 0 is conventionally reserved for background.
RF-DETR follows that, so `robot` is category 1 here even though it is class 0 in YOLO.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConvertStats:
    images: int = 0
    boxes: int = 0
    skipped_unreadable: int = 0
    skipped_degenerate: int = 0
    per_split: dict = field(default_factory=dict)


def _image_size(path: Path) -> tuple[int, int] | None:
    import cv2
    img = cv2.imread(str(path))
    if img is None:
        return None
    return img.shape[1], img.shape[0]


def convert_split(
    images_dir: Path,
    labels_dir: Path,
    out_json: Path,
    class_name: str = "robot",
    stats: ConvertStats | None = None,
) -> dict:
    """Write one split's `_annotations.coco.json` and return it."""
    stats = stats or ConvertStats()

    images: list[dict] = []
    annotations: list[dict] = []
    image_id = 1
    ann_id = 1

    for image_path in sorted(images_dir.iterdir()):
        if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        size = _image_size(image_path)
        if size is None:
            stats.skipped_unreadable += 1
            continue
        width, height = size

        images.append({
            "id": image_id,
            "file_name": image_path.name,
            "width": width,
            "height": height,
        })
        stats.images += 1

        label_path = labels_dir / f"{image_path.stem}.txt"
        if label_path.exists():
            for line in label_path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                _, cx, cy, bw, bh = parts[:5]
                cx, cy, bw, bh = float(cx), float(cy), float(bw), float(bh)

                # Normalised centre+size -> absolute top-left+size.
                x = (cx - bw / 2) * width
                y = (cy - bh / 2) * height
                w = bw * width
                h = bh * height

                # Clamp to the image. A box escaping the frame is not an error worth discarding,
                # but a zero-area one is: COCO consumers divide by area.
                x, y = max(0.0, x), max(0.0, y)
                w, h = min(w, width - x), min(h, height - y)
                if w <= 1.0 or h <= 1.0:
                    stats.skipped_degenerate += 1
                    continue

                annotations.append({
                    "id": ann_id,
                    "image_id": image_id,
                    "category_id": 1,          # COCO reserves 0 for background
                    "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                    "area": round(w * h, 2),
                    "iscrowd": 0,
                })
                ann_id += 1
                stats.boxes += 1

        image_id += 1

    document = {
        "info": {"description": "Project Tengen - FRC robot detection"},
        "licenses": [{"id": 1, "name": "CC BY 4.0",
                      "url": "https://creativecommons.org/licenses/by/4.0/"}],
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": class_name, "supercategory": "none"}],
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(document), encoding="utf-8")
    stats.per_split[images_dir.parent.name] = (len(images), len(annotations))
    return document
