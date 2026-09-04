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

Splits are REBUILT, not preserved, and that is a reversal of the obvious choice. Preserving a
published split is normally right. It is wrong here, because both source datasets already leak:

    dark eden   109 source images in both train and valid, 58 train/test, 34 valid/test
    WorBots      94 source images in both train and valid, 47 train/test, 29 valid/test

Roboflow augments a source image into several copies and assigns the copies independently, so a
flipped, blurred version of a validation image ends up in training. Any accuracy measured against
such a split is inflated -- which is worth remembering when reading WorBots' published mAP@50 of
97.6%.

So copies are grouped back to their source image by filename (`<stem>_jpg.rf.<hash>.jpg`), one
copy per source is kept, and whole groups are assigned to a split by a hash of the stem. That is
the same rule the rest of this project uses for matches: the indivisible unit goes to exactly one
side, always.

Dropping the extra copies also drops the augmentation baked into them, which is the point. The
trainer applies its own conservative augmentation -- horizontal flips and mild brightness -- and
deliberately avoids the vertical flips and heavy rotations these exports contain, because
upside-down FRC footage does not exist.
"""

from __future__ import annotations

import json
import re
import shutil
import zlib
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
    sources_in: int = 0
    sources_kept: int = 0
    copies_dropped: int = 0
    images_in: int = 0
    images_kept: int = 0
    images_without_robots: int = 0
    boxes_in: int = 0
    boxes_kept: int = 0
    dropped_classes: Counter = field(default_factory=Counter)
    kept_classes: Counter = field(default_factory=Counter)
    per_split: Counter = field(default_factory=Counter)



# --------------------------------------------------------------------------- source grouping

#: Roboflow encodes augmented copies as `<source stem>_<ext>.rf.<hash>.<ext>`, so the stem
#: recovers which copies came from one photograph.
_ROBOFLOW_COPY = re.compile(r"(.+?)_(jpg|jpeg|png)\.rf\.[0-9a-f]+\.", re.IGNORECASE)


def source_stem(filename: str) -> str:
    """The original image a Roboflow copy came from, or the filename if it is not a copy."""
    match = _ROBOFLOW_COPY.match(filename)
    return match.group(1) if match else Path(filename).stem


def assign_split(stem: str, train: float = 0.80, valid: float = 0.10) -> str:
    """Deterministically place a source image, so a rerun reproduces the same dataset.

    Hashing the stem rather than shuffling means the assignment does not depend on file order,
    on how many sources there are, or on which datasets were merged in the same run.
    """
    bucket = (zlib.crc32(stem.encode("utf-8")) % 10_000) / 10_000
    if bucket < train:
        return "train"
    if bucket < train + valid:
        return "valid"
    return "test"


def group_by_source(root: Path) -> dict[str, list[tuple[Path, Path]]]:
    """Map source stem -> [(image, label)] across every published split.

    Deliberately ignores which split the source put a copy in. That information is what is being
    discarded, because it is what carries the leak.

    A flat `images/` + `labels/` pair is also accepted. That is the shape a human labelling pack
    comes back in -- labellers should not have to think about splits, and this function is going
    to reassign them anyway. Without it a returned pack merges to silently nothing.
    """
    groups: dict[str, list[tuple[Path, Path]]] = {}
    layouts = [(root / split / "images", root / split / "labels")
               for split in ("train", "valid", "test")]
    layouts.append((root / "images", root / "labels"))
    for images_dir, labels_dir in layouts:
        if not images_dir.is_dir():
            continue
        for image in sorted(images_dir.iterdir()):
            if image.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            groups.setdefault(source_stem(image.name), []).append(
                (image, labels_dir / f"{image.stem}.txt")
            )
    return groups


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
    copies_per_source: int = 1,
) -> None:
    """Merge one YOLO dataset into the output, regrouped by source image and re-split.

    The published split is discarded on purpose -- see the module docstring. Every augmented copy
    of a photograph is gathered, `copies_per_source` of them are kept, and the whole group lands
    in one split chosen by hashing the source stem.

    `prefix` namespaces filenames, because two datasets can contain the same source stem and one
    would otherwise silently overwrite the other.
    """
    for split in ("train", "valid", "test"):
        (out_dir / split / "images").mkdir(parents=True, exist_ok=True)
        (out_dir / split / "labels").mkdir(parents=True, exist_ok=True)

    for stem, copies in sorted(group_by_source(root).items()):
        split = assign_split(f"{prefix}/{stem}")
        stats.sources_in += 1

        written_for_source = 0
        for image, label_path in copies:
            stats.images_in += 1
            if written_for_source >= copies_per_source:
                stats.copies_dropped += 1
                continue

            rows = _read_yolo_labels(label_path)
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
                # Its only labels were game pieces. That is an unlabelled image, not a negative
                # example -- writing it would assert "no robots here", which the source never said.
                stats.images_without_robots += 1
                continue

            target = f"{prefix}_{image.name}"
            shutil.copy2(image, out_dir / split / "images" / target)
            (out_dir / split / "labels" / f"{prefix}_{image.stem}.txt").write_text(
                "".join(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for cx, cy, w, h in kept),
                encoding="utf-8",
            )
            stats.images_kept += 1
            stats.boxes_kept += len(kept)
            stats.per_split[split] += 1
            written_for_source += 1

        if written_for_source:
            stats.sources_kept += 1


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


def main(argv=None) -> int:
    """Merge YOLO datasets into one, regrouped by source image and re-split.

    Exists so the documented way to fold returned human labels back in is a command someone can
    actually run. The merging itself was already here; only the entry point was missing.

        python -m ingest.collection.dataset_merge --into data/datasets/frc-robots-v3 \
            data/datasets/frc-robots-v2 data/label-packs/v3-viewpoint
    """
    import argparse

    parser = argparse.ArgumentParser(description="Merge YOLO datasets, re-splitting by source.")
    parser.add_argument("sources", nargs="+", type=Path, help="YOLO dataset roots to merge")
    parser.add_argument("--into", required=True, type=Path, help="new output directory")
    parser.add_argument("--keep-empty", action="store_true",
                        help="keep images whose label file is empty; they teach 'no robots here'")
    parser.add_argument("--copies-per-source", type=int, default=1,
                        help="augmented copies to keep per source photograph")
    args = parser.parse_args(argv)

    if args.into.exists() and any(args.into.iterdir()):
        # Never overwrite a dataset: a reviewed one cannot be rebuilt, and a silently merged one
        # cannot be told apart from the version a model was trained on.
        print(f"{args.into} already exists and is not empty. Use a new directory.")
        return 1

    stats = MergeStats()
    for source in args.sources:
        if not source.is_dir():
            print(f"not a directory: {source}")
            return 1
        names = read_yolo_names(source) or ["robot"]
        merge_yolo_source(source, names, args.into, source.name, stats,
                          keep_empty=args.keep_empty,
                          copies_per_source=args.copies_per_source)
        print(f"  merged {source}  (classes: {', '.join(names)})")

    write_dataset_yaml(args.into)
    print(f"\nsources {stats.sources_in} -> kept {stats.sources_kept}")
    print(f"images  {stats.images_in} -> kept {stats.images_kept}")
    print(f"boxes   {stats.boxes_in}")
    if stats.images_without_robots:
        print(f"{stats.images_without_robots} images had no robot labels and were "
              f"{'kept' if args.keep_empty else 'dropped'}")
    if stats.dropped_classes:
        print("dropped classes: " + ", ".join(f"{k} {v}" for k, v in sorted(
            stats.dropped_classes.items())))
    print(f"\nwrote {args.into}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
