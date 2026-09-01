"""Merge third-party FRC datasets down to this project's single `robot` class.

Community FRC datasets label different things. One uses a single `robot` class; another splits
robots by alliance (`red_robot`, `blue_robot`, `black_robot`) and also labels game pieces, field
displays and speakers that we do not care about. Training a robot detector on all of it teaches
the model that a speaker is a kind of robot.

So this does two jobs:

  * keep only annotations whose class names describe a robot, and
  * rewrite them all to class 0, `robot`, matching contracts/ and the rest of the pipeline.

Alliance colour is deliberately discarded for now, and deliberately RECORDED while discarding, in
`alliance_hint` on each COCO annotation. Per-robot attribution is a later goal and that colour is
a free head start on it -- throwing the information away silently would be the wasteful choice.

Splits are preserved as the source published them. A merge is not the moment to reshuffle: these
are separate corpora, and re-splitting across them can put near-identical augmented copies of one
source image on both sides of the train/valid line.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

#: Class names that mean "an FRC robot", lowercased. Anything else in a source dataset is dropped.
#: Matching is on whole words so `speaker_blue` cannot match via `blue`.
ROBOT_ALIASES = {
    "robot", "robots", "robo", "robos",
    "red_robot", "blue_robot", "black_robot",
    "red-robot", "blue-robot", "black-robot",
    "redbot", "bluebot", "red-bot", "blue-bot",
    "frc-robot", "frc_robot", "frcrobot", "frc-robots",
    "red_bumper", "blue_bumper", "red bumper", "blue bumper",
}

#: Alliance recorded rather than discarded, for later team attribution work.
ALLIANCE_BY_TOKEN = {"red": "red", "blue": "blue", "black": "unknown"}


def is_robot_class(name: str) -> bool:
    return name.strip().lower().replace(" ", "_").replace("-", "_") in {
        a.replace(" ", "_").replace("-", "_") for a in ROBOT_ALIASES
    }


def alliance_of(name: str) -> str | None:
    tokens = name.strip().lower().replace("-", "_").split("_")
    for token in tokens:
        if token in ALLIANCE_BY_TOKEN:
            return ALLIANCE_BY_TOKEN[token]
    return None


@dataclass
class MergeStats:
    images_in: int = 0
    images_kept: int = 0
    images_without_robots: int = 0
    boxes_in: int = 0
    boxes_kept: int = 0
    dropped_classes: Counter = field(default_factory=Counter)
    kept_classes: Counter = field(default_factory=Counter)
    per_split: Counter = field(default_factory=Counter)


def _read_yolo_labels(label_path: Path) -> list[tuple[int, float, float, float, float]]:
    if not label_path.exists():
        return []
    rows = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 5:
            rows.append((int(parts[0]), *(float(v) for v in parts[1:5])))
    return rows


def merge_yolo_source(
    root: Path,
    names: list[str],
    out_dir: Path,
    prefix: str,
    stats: MergeStats,
    keep_empty: bool = False,
) -> None:
    """Copy one YOLO-format dataset into the merged output, remapped to a single class.

    `prefix` namespaces filenames so two sources cannot collide -- Roboflow exports hash their
    names, but two hashes of the same source image would otherwise overwrite each other.
    """
    for split in ("train", "valid", "test"):
        images_dir = root / split / "images"
        labels_dir = root / split / "labels"
        if not images_dir.is_dir():
            continue

        (out_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (out_dir / split / "labels").mkdir(parents=True, exist_ok=True)

        for image in sorted(images_dir.iterdir()):
            if image.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            stats.images_in += 1
            rows = _read_yolo_labels(labels_dir / f"{image.stem}.txt")
            stats.boxes_in += len(rows)

            kept = []
            for cls, cx, cy, w, h in rows:
                name = names[cls] if 0 <= cls < len(names) else str(cls)
                if is_robot_class(name):
                    kept.append((cx, cy, w, h))
                    stats.kept_classes[name] += 1
                else:
                    stats.dropped_classes[name] += 1

            if not kept and not keep_empty:
                # An image whose only labels were speakers and game pieces is not a negative
                # example of a robot -- it is an unlabelled image, and training on it as though
                # it contained no robots would teach the detector to miss them.
                stats.images_without_robots += 1
                continue

            target_name = f"{prefix}_{image.name}"
            shutil.copy2(image, out_dir / split / "images" / target_name)
            label_out = out_dir / split / "labels" / f"{prefix}_{image.stem}.txt"
            label_out.write_text(
                "".join(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for cx, cy, w, h in kept),
                encoding="utf-8",
            )
            stats.images_kept += 1
            stats.boxes_kept += len(kept)
            stats.per_split[split] += 1


def read_yolo_names(root: Path) -> list[str]:
    """Class names from data.yaml without requiring a YAML dependency.

    Roboflow writes a flat `names: ['a', 'b']` line, which is the only shape needed here.
    """
    for candidate in (root / "data.yaml", root / "data.yml"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("names:") and "[" in stripped:
                inner = stripped.split("[", 1)[1].rsplit("]", 1)[0]
                return [n.strip().strip("'\"") for n in inner.split(",") if n.strip()]
    return []


def write_dataset_yaml(out_dir: Path) -> None:
    (out_dir / "data.yaml").write_text(
        "train: ../train/images\n"
        "val: ../valid/images\n"
        "test: ../test/images\n"
        "\n"
        "nc: 1\n"
        "names: ['robot']\n",
        encoding="utf-8",
    )
