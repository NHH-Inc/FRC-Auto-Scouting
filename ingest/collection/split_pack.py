"""Split a labelling pack into per-person zips.

One 232 MB archive is the wrong shape for this job twice over. It is too large to send through
the places volunteers actually are -- Discord takes 10 MB from a free account, 25 with Nitro --
and it gives ten people the same 400 frames with no way to divide them, so the work is either
duplicated or negotiated by hand.

Chunks fix both. Each one is self-contained: its own images, labels, instructions and manifest,
so a labeller unzips it and starts, and hands back the same folder. Nobody needs to know what
anyone else has.

Frames are dealt round-robin rather than sliced in order, so every chunk covers many venues. That
matters because chunks come back at different times, or not at all: a chunk that is one arena is
worth much less than the same count spread across twenty, and partial returns are the normal case
with volunteers.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

#: Under Discord's 25 MB Nitro limit and comfortable to download on a phone hotspot at a venue.
TARGET_MB = 23.0


@dataclass
class Chunk:
    index: int
    stems: list[str]

    @property
    def name(self) -> str:
        return f"tengen-labels-{self.index:02d}"


def deal(stems: list[str], chunks: int) -> list[Chunk]:
    """Deal frames round-robin so every chunk spans many venues.

    Slicing in order would hand chunk 1 every frame from the first venues and chunk 10 every frame
    from the last. Since chunks come back separately, and some never come back at all, each one
    has to be a usable sample on its own.
    """
    if chunks <= 0 or not stems:
        return []
    chunks = min(chunks, len(stems))
    buckets: list[list[str]] = [[] for _ in range(chunks)]
    for position, stem in enumerate(sorted(stems)):
        buckets[position % chunks].append(stem)
    return [Chunk(i + 1, sorted(b)) for i, b in enumerate(buckets) if b]


def chunk_readme(chunk: Chunk, total_chunks: int, base_instructions: str) -> str:
    return (
        f"# Tengen labelling — pack {chunk.index} of {total_chunks}\n\n"
        f"**This pack: {len(chunk.stems)} images.** They are yours; nobody else has them, so\n"
        f"nothing you do here is duplicated work.\n\n"
        f"When you are finished, send back the whole `{chunk.name}` folder — or just the\n"
        f"`labels/` folder inside it, which is all we actually read. Keep the filenames exactly as\n"
        f"they are; they are how each label finds its image.\n\n"
        f"If you only get through part of it, send it anyway and say how far you got. Half a pack\n"
        f"of properly labelled images is genuinely useful. Half-labelled *images* are not — see\n"
        f"the rule below.\n\n"
        f"---\n\n" + base_instructions
    )


def write_chunks(pack: Path, out_dir: Path, chunks: int, compress: bool = True) -> list[dict]:
    """Write one zip per chunk. Returns a summary per chunk."""
    stems = sorted(p.stem for p in (pack / "images").glob("*.jpg"))
    if not stems:
        return []
    base = (pack / "README.md").read_text(encoding="utf-8")
    manifest = {}
    manifest_path = pack / "manifest.json"
    if manifest_path.exists():
        for item in json.loads(manifest_path.read_text(encoding="utf-8")).get("items", []):
            manifest[Path(item["image"]).stem] = item

    out_dir.mkdir(parents=True, exist_ok=True)
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    parts = deal(stems, chunks)
    summary = []
    for chunk in parts:
        target = out_dir / f"{chunk.name}.zip"
        with zipfile.ZipFile(target, "w", mode) as archive:
            for stem in chunk.stems:
                archive.write(pack / "images" / f"{stem}.jpg", f"{chunk.name}/images/{stem}.jpg")
                label = pack / "labels" / f"{stem}.txt"
                # An image without its label file reads as "no robots here", so one is always
                # written even when the detector proposed nothing.
                archive.writestr(f"{chunk.name}/labels/{stem}.txt",
                                 label.read_text(encoding="utf-8") if label.exists() else "")
            archive.writestr(f"{chunk.name}/README.md",
                             chunk_readme(chunk, len(parts), base))
            archive.writestr(f"{chunk.name}/data.yaml",
                             "path: .\ntrain: images\nval: images\nnc: 1\nnames: [robot]\n")
            archive.writestr(f"{chunk.name}/manifest.json", json.dumps({
                "schema_version": 3,
                "pack": chunk.name,
                "of": len(parts),
                "frames": len(chunk.stems),
                "items": [manifest.get(s, {"image": f"images/{s}.jpg"}) for s in chunk.stems],
            }, indent=2))
        venues = {s.rsplit("_", 3)[0] for s in chunk.stems}
        summary.append({
            "name": chunk.name,
            "path": str(target),
            "frames": len(chunk.stems),
            "venues": len(venues),
            "megabytes": round(target.stat().st_size / (1024 * 1024), 1),
        })
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--chunks", type=int, default=0,
                        help="how many people are labelling; 0 sizes chunks to about "
                             f"{TARGET_MB:.0f} MB so they send anywhere")
    parser.add_argument("--no-compress", action="store_true",
                        help="skip deflate; JPEGs barely compress and this is much faster")
    args = parser.parse_args(argv)

    images = sorted((args.pack / "images").glob("*.jpg"))
    if not images:
        print(f"no images under {args.pack / 'images'}")
        return 1

    chunks = args.chunks
    if chunks <= 0:
        total_mb = sum(p.stat().st_size for p in images) / (1024 * 1024)
        chunks = max(1, round(total_mb / TARGET_MB))
        print(f"{len(images)} images, {total_mb:.0f} MB -> {chunks} chunks of about "
              f"{TARGET_MB:.0f} MB")

    summary = write_chunks(args.pack, args.out, chunks, compress=not args.no_compress)
    print(f"\n{'zip':<26} {'frames':>7} {'venues':>7} {'MB':>6}")
    for row in summary:
        print(f"{row['name'] + '.zip':<26} {row['frames']:>7} {row['venues']:>7} "
              f"{row['megabytes']:>6.1f}")
    print(f"\n{len(summary)} zips in {args.out}. Send one per person; each is self-contained "
          f"and none overlap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
