"""YOLO to COCO conversion.

This is a coordinate-system change, not a reformat. The dangerous failure is a box that is the
right size in the wrong place: nothing errors, and a model trains happily on the wrong answer. So
these tests check actual arithmetic against hand-computed values rather than just structure.
"""

import json
import tempfile
import unittest
from pathlib import Path

from ingest.collection.yolo_to_coco import ConvertStats, convert_split


def _split(root: Path, size=(200, 100), labels: dict[str, list[str]] | None = None) -> tuple[Path, Path]:
    import cv2
    import numpy as np

    images, lbls = root / "images", root / "labels"
    images.mkdir(parents=True)
    lbls.mkdir(parents=True)
    for stem, rows in (labels or {}).items():
        cv2.imwrite(str(images / f"{stem}.jpg"),
                    np.full((size[1], size[0], 3), 128, dtype=np.uint8))
        (lbls / f"{stem}.txt").write_text("\n".join(rows), encoding="utf-8")
    return images, lbls


class CoordinateTests(unittest.TestCase):
    def test_centre_and_size_become_top_left_and_size_in_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            # 200x100 image. Centre at (0.5, 0.5) = (100, 50). Size 0.2x0.4 = 40x40 px.
            # So top-left should be (100-20, 50-20) = (80, 30).
            imgs, lbls = _split(root, (200, 100), {"a": ["0 0.5 0.5 0.2 0.4"]})
            doc = convert_split(imgs, lbls, root / "_annotations.coco.json")

            self.assertEqual(doc["annotations"][0]["bbox"], [80.0, 30.0, 40.0, 40.0])
            self.assertEqual(doc["annotations"][0]["area"], 1600.0)

    def test_image_dimensions_are_read_not_assumed(self):
        # A dataset resized by one tool and cropped by another has mixed sizes and says nothing.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            imgs, lbls = _split(root, (640, 480), {"a": ["0 0.5 0.5 0.5 0.5"]})
            doc = convert_split(imgs, lbls, root / "_annotations.coco.json")

            self.assertEqual(doc["images"][0]["width"], 640)
            self.assertEqual(doc["images"][0]["height"], 480)
            self.assertEqual(doc["annotations"][0]["bbox"], [160.0, 120.0, 320.0, 240.0])

    def test_a_box_running_off_the_edge_is_clamped_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            imgs, lbls = _split(root, (100, 100), {"a": ["0 0.05 0.5 0.4 0.4"]})
            doc = convert_split(imgs, lbls, root / "_annotations.coco.json")
            x, y, w, h = doc["annotations"][0]["bbox"]
            self.assertGreaterEqual(x, 0.0)
            self.assertLessEqual(x + w, 100.0)

    def test_a_zero_area_box_is_discarded(self):
        # COCO consumers divide by area.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            imgs, lbls = _split(root, (100, 100), {"a": ["0 0.5 0.5 0.001 0.001"]})
            stats = ConvertStats()
            doc = convert_split(imgs, lbls, root / "_annotations.coco.json", stats=stats)
            self.assertEqual(doc["annotations"], [])
            self.assertEqual(stats.skipped_degenerate, 1)


class StructureTests(unittest.TestCase):
    def test_category_id_is_one_because_coco_reserves_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            imgs, lbls = _split(root, labels={"a": ["0 0.5 0.5 0.2 0.2"]})
            doc = convert_split(imgs, lbls, root / "_annotations.coco.json")
            self.assertEqual(doc["categories"][0]["id"], 1)
            self.assertEqual(doc["categories"][0]["name"], "robot")
            self.assertEqual(doc["annotations"][0]["category_id"], 1)

    def test_annotations_point_at_real_image_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            imgs, lbls = _split(root, labels={
                "a": ["0 0.5 0.5 0.2 0.2"], "b": ["0 0.3 0.3 0.1 0.1", "0 0.7 0.7 0.1 0.1"]})
            doc = convert_split(imgs, lbls, root / "_annotations.coco.json")
            ids = {i["id"] for i in doc["images"]}
            for ann in doc["annotations"]:
                self.assertIn(ann["image_id"], ids)

    def test_an_image_with_no_label_file_still_appears(self):
        # RF-DETR needs the image listed even with no boxes, or the split count drifts.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            imgs, lbls = _split(root, labels={"a": ["0 0.5 0.5 0.2 0.2"]})
            (lbls / "a.txt").unlink()
            doc = convert_split(imgs, lbls, root / "_annotations.coco.json")
            self.assertEqual(len(doc["images"]), 1)
            self.assertEqual(doc["annotations"], [])

    def test_the_file_it_writes_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "train"
            imgs, lbls = _split(root, labels={"a": ["0 0.5 0.5 0.2 0.2"]})
            out = root / "_annotations.coco.json"
            convert_split(imgs, lbls, out)
            json.loads(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
