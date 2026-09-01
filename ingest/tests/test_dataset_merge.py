"""Merging third-party datasets down to one robot class.

The failure that matters is silent: keeping a `speaker_blue` box as a robot, or writing an image
whose only labels were game pieces as though it contained no robots. Both teach the detector
something false, and neither raises an error.
"""

import tempfile
import unittest
from pathlib import Path

from ingest.collection.dataset_merge import (
    MergeStats,
    alliance_of,
    is_robot_class,
    merge_yolo_source,
    read_yolo_names,
    write_dataset_yaml,
)


class ClassMatchingTests(unittest.TestCase):
    def test_recognises_the_common_robot_spellings(self):
        for name in ("robot", "robots", "red_robot", "blue-robot", "BlueBot", "frc-robot"):
            self.assertTrue(is_robot_class(name), name)

    def test_rejects_game_pieces_and_field_furniture(self):
        for name in ("note", "notes", "coral", "algae", "speaker_blue",
                     "subwoofer_red", "blue_display", "cone", "cube", "cage"):
            self.assertFalse(is_robot_class(name), name)

    def test_speaker_blue_does_not_match_via_the_word_blue(self):
        # Substring matching would let every alliance-coloured field element in.
        self.assertFalse(is_robot_class("speaker_blue"))
        self.assertTrue(is_robot_class("blue_robot"))

    def test_alliance_is_recorded_not_guessed(self):
        self.assertEqual(alliance_of("red_robot"), "red")
        self.assertEqual(alliance_of("blue-robot"), "blue")
        self.assertEqual(alliance_of("black_robot"), "unknown")
        self.assertIsNone(alliance_of("robot"))


def _make_source(root: Path, names_line: str, rows_by_image: dict[str, list[str]]) -> None:
    (root / "train" / "images").mkdir(parents=True)
    (root / "train" / "labels").mkdir(parents=True)
    (root / "data.yaml").write_text(f"nc: 1\nnames: {names_line}\n", encoding="utf-8")
    for stem, rows in rows_by_image.items():
        (root / "train" / "images" / f"{stem}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (root / "train" / "labels" / f"{stem}.txt").write_text("\n".join(rows), encoding="utf-8")


class MergeTests(unittest.TestCase):
    def test_keeps_robots_and_drops_everything_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "src", Path(tmp) / "out"
            _make_source(src, "['blue_robot', 'note', 'speaker_blue']", {
                "a": ["0 0.5 0.5 0.1 0.2", "1 0.2 0.2 0.05 0.05"],   # one robot, one note
                "b": ["2 0.3 0.3 0.1 0.1"],                          # speaker only
            })
            stats = MergeStats()
            merge_yolo_source(src, ["blue_robot", "note", "speaker_blue"], out, "s1", stats)

            self.assertEqual(stats.boxes_in, 3)
            self.assertEqual(stats.boxes_kept, 1)
            self.assertEqual(stats.dropped_classes["note"], 1)
            self.assertEqual(stats.dropped_classes["speaker_blue"], 1)

    def test_an_image_with_no_robots_is_excluded_not_kept_empty(self):
        # Keeping it would assert "no robots here", which is a claim the source never made.
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "src", Path(tmp) / "out"
            _make_source(src, "['note']", {"only_a_note": ["0 0.3 0.3 0.1 0.1"]})
            stats = MergeStats()
            merge_yolo_source(src, ["note"], out, "s1", stats)

            self.assertEqual(stats.images_kept, 0)
            self.assertEqual(stats.images_without_robots, 1)
            self.assertFalse(list((out / "train" / "images").glob("*.jpg")))

    def test_every_kept_box_is_rewritten_to_class_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "src", Path(tmp) / "out"
            _make_source(src, "['note', 'red_robot']", {"a": ["1 0.5 0.5 0.1 0.2"]})
            stats = MergeStats()
            merge_yolo_source(src, ["note", "red_robot"], out, "s1", stats)

            written = (out / "train" / "labels" / "s1_a.txt").read_text(encoding="utf-8")
            self.assertTrue(written.startswith("0 "), written)

    def test_prefix_stops_two_sources_overwriting_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            for i, prefix in enumerate(("s1", "s2")):
                src = Path(tmp) / f"src{i}"
                _make_source(src, "['robot']", {"same_name": ["0 0.5 0.5 0.1 0.2"]})
                merge_yolo_source(src, ["robot"], out, prefix, MergeStats())
            files = sorted(p.name for p in (out / "train" / "images").glob("*.jpg"))
            self.assertEqual(files, ["s1_same_name.jpg", "s2_same_name.jpg"])

    def test_reads_class_names_from_roboflow_data_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.yaml").write_text(
                "train: ../train/images\nnc: 2\nnames: ['algae', 'coral']\n", encoding="utf-8")
            self.assertEqual(read_yolo_names(root), ["algae", "coral"])

    def test_output_yaml_declares_exactly_one_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_dataset_yaml(out)
            text = (out / "data.yaml").read_text(encoding="utf-8")
            self.assertIn("nc: 1", text)
            self.assertIn("names: ['robot']", text)


if __name__ == "__main__":
    unittest.main()
