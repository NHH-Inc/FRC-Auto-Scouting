"""Splitting a labelling pack into per-person zips.

Two failures here would be invisible until the labels came back: a frame that lands in two
people's chunks wastes half of somebody's evening, and a frame in nobody's chunk is silently
never labelled at all.
"""

import json
import zipfile

import pytest

from ingest.collection.split_pack import deal, write_chunks


def make_pack(root, frames):
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir(parents=True)
    for stem in frames:
        (root / "images" / f"{stem}.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")
        (root / "labels" / f"{stem}.txt").write_text("0 0.5 0.5 0.1 0.1\n")
    (root / "README.md").write_text("# instructions\nBox every robot, or skip the image.\n")
    (root / "manifest.json").write_text(json.dumps({
        "items": [{"image": f"images/{s}.jpg", "human_review_required": True} for s in frames]
    }))
    return root


FRAMES = [f"venue{v}_{t:05d}" for v in range(6) for t in range(4)]   # 24 frames, 6 venues


class TestDeal:
    def test_every_frame_lands_in_exactly_one_chunk(self):
        chunks = deal(FRAMES, 4)
        seen = [stem for c in chunks for stem in c.stems]
        assert sorted(seen) == sorted(FRAMES)
        assert len(seen) == len(set(seen))

    def test_chunks_span_venues_rather_than_slicing_them(self):
        # Chunks come back at different times and some never come back. A chunk that is one
        # arena is worth far less than the same count spread across many.
        chunks = deal(FRAMES, 4)
        for chunk in chunks:
            venues = {s.split("_")[0] for s in chunk.stems}
            assert len(venues) >= 3, f"{chunk.name} covers only {venues}"

    def test_chunks_are_close_to_even(self):
        sizes = [len(c.stems) for c in deal(FRAMES, 5)]
        assert max(sizes) - min(sizes) <= 1

    def test_more_chunks_than_frames_does_not_make_empty_ones(self):
        chunks = deal(FRAMES[:3], 10)
        assert len(chunks) == 3
        assert all(c.stems for c in chunks)

    def test_degenerate_inputs(self):
        assert deal([], 4) == []
        assert deal(FRAMES, 0) == []


class TestWriteChunks:
    def test_each_zip_is_self_contained(self, tmp_path):
        pack = make_pack(tmp_path / "pack", FRAMES)
        summary = write_chunks(pack, tmp_path / "out", 3)
        assert len(summary) == 3
        for row in summary:
            with zipfile.ZipFile(row["path"]) as archive:
                names = archive.namelist()
                assert any(n.endswith("README.md") for n in names)
                assert any(n.endswith("data.yaml") for n in names)
                assert any(n.endswith("manifest.json") for n in names)

    def test_every_image_ships_with_its_label(self, tmp_path):
        # An image without its .txt is read by the trainer as a frame with no robots in it.
        pack = make_pack(tmp_path / "pack", FRAMES)
        write_chunks(pack, tmp_path / "out", 3)
        for zip_path in sorted((tmp_path / "out").glob("*.zip")):
            with zipfile.ZipFile(zip_path) as archive:
                images = {n.rsplit("/", 1)[1][:-4] for n in archive.namelist()
                          if n.endswith(".jpg")}
                labels = {n.rsplit("/", 1)[1][:-4] for n in archive.namelist()
                          if "/labels/" in n}
                assert images == labels

    def test_a_missing_label_becomes_an_empty_one_not_a_gap(self, tmp_path):
        pack = make_pack(tmp_path / "pack", FRAMES)
        (pack / "labels" / f"{FRAMES[0]}.txt").unlink()
        write_chunks(pack, tmp_path / "out", 2)
        found = False
        for zip_path in (tmp_path / "out").glob("*.zip"):
            with zipfile.ZipFile(zip_path) as archive:
                for name in archive.namelist():
                    if name.endswith(f"labels/{FRAMES[0]}.txt"):
                        assert archive.read(name) == b""
                        found = True
        assert found, "the frame whose label was missing never shipped"

    def test_no_frame_is_in_two_zips(self, tmp_path):
        pack = make_pack(tmp_path / "pack", FRAMES)
        write_chunks(pack, tmp_path / "out", 4)
        seen = []
        for zip_path in (tmp_path / "out").glob("*.zip"):
            with zipfile.ZipFile(zip_path) as archive:
                seen += [n for n in archive.namelist() if n.endswith(".jpg")]
        stems = [n.rsplit("/", 1)[1] for n in seen]
        assert len(stems) == len(set(stems)) == len(FRAMES)

    def test_the_chunk_readme_says_which_pack_it_is(self, tmp_path):
        pack = make_pack(tmp_path / "pack", FRAMES)
        write_chunks(pack, tmp_path / "out", 3)
        with zipfile.ZipFile(tmp_path / "out" / "tengen-labels-01.zip") as archive:
            readme = archive.read("tengen-labels-01/README.md").decode()
        assert "pack 1 of 3" in readme
        # The original instructions must survive into every chunk, not just the parent folder.
        assert "Box every robot" in readme

    def test_an_empty_pack_produces_nothing_rather_than_an_empty_zip(self, tmp_path):
        (tmp_path / "pack" / "images").mkdir(parents=True)
        (tmp_path / "pack" / "README.md").write_text("x")
        assert write_chunks(tmp_path / "pack", tmp_path / "out", 3) == []
