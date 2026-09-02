"""Self-training rails.

Every test here guards against the same failure: a model's mistake becoming a training label and
being learned more confidently than the original error. None of these failures raise.
"""

import json
import tempfile
import unittest
from pathlib import Path

from ingest.collection.pseudo_label import (
    PseudoStats, enforce_ratio, select_frames, write_yolo)


def _collection(root: Path, rows: list[dict]) -> Path:
    import cv2, numpy as np
    (root / "frames").mkdir(parents=True)
    frames = []
    for i, row in enumerate(rows):
        fid = row["frame_id"]
        cv2.imwrite(str(root / "frames" / f"{fid}.jpg"), np.full((90,160,3), 120, np.uint8))
        frames.append({"frame_id": fid, "image_path": f"frames/{fid}.jpg", "quality_ok": True})
    (root / "frames.jsonl").write_text("".join(json.dumps(f)+"\n" for f in frames), encoding="utf-8")
    (root / "detector-consensus.jsonl").write_text(
        "".join(json.dumps(r)+"\n" for r in rows), encoding="utf-8")
    return root


def row(fid, boxes, detectors=("yolo11", "rfdetr")):
    return {"frame_id": fid, "detectors": list(detectors), "boxes": boxes}


def box(conf, agree=2, x=0.3, y=0.4):
    return {"x": x, "y": y, "w": 0.08, "h": 0.12, "confidence": conf, "agreement_count": agree}


class SelectionTests(unittest.TestCase):
    def test_low_confidence_boxes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [row("a", [box(0.45), box(0.75)])])
            s = PseudoStats()
            chosen = select_frames([col], stats=s)
            self.assertEqual(s.boxes_kept, 1)
            self.assertEqual(s.rejected_low_confidence, 1)

    def test_a_box_only_one_detector_found_is_rejected(self):
        # The only evidence not produced by the model being retrained is another model agreeing.
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [row("a", [box(0.95, agree=1)])])
            s = PseudoStats()
            select_frames([col], stats=s)
            self.assertEqual(s.boxes_kept, 0)
            self.assertEqual(s.rejected_low_agreement, 1)

    def test_a_frame_claiming_more_robots_than_exist_is_discarded_entirely(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [row("a", [box(0.9, x=0.05*i) for i in range(10)])])
            s = PseudoStats()
            self.assertEqual(select_frames([col], stats=s), [])
            self.assertEqual(s.frames_over_cap, 1)

    def test_running_with_one_detector_is_recorded_as_unsafe(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [row("a", [box(0.9, agree=1)], detectors=("yolo11",))])
            s = PseudoStats()
            select_frames([col], min_agreement=1, stats=s)
            self.assertTrue(s.single_detector, "a single-detector run must be visible in the stats")


class RatioTests(unittest.TestCase):
    def test_pseudo_labels_cannot_outnumber_human_labels(self):
        chosen = list(range(1000))
        s = PseudoStats()
        kept = enforce_ratio(chosen, human_image_count=100, max_ratio=0.5, stats=s)
        self.assertEqual(len(kept), 50)
        self.assertEqual(s.dropped_by_ratio, 950)

    def test_a_small_selection_passes_through_untouched(self):
        self.assertEqual(enforce_ratio([1, 2, 3], human_image_count=100), [1, 2, 3])

    def test_trimming_is_deterministic(self):
        a = enforce_ratio(list(range(500)), 100)
        b = enforce_ratio(list(range(500)), 100)
        self.assertEqual(a, b)


class WriteTests(unittest.TestCase):
    def test_everything_lands_in_train_never_valid_or_test(self):
        # Validating against a predecessor's output measures agreement, not correctness.
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp) / "c", [row("a", [box(0.9)])])
            out = Path(tmp) / "out"
            write_yolo(select_frames([col]), out)
            self.assertTrue((out / "train" / "images").is_dir())
            self.assertFalse((out / "valid").exists())
            self.assertFalse((out / "test").exists())

    def test_output_is_marked_as_machine_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp) / "c", [row("a", [box(0.9)])])
            out = Path(tmp) / "out"
            write_yolo(select_frames([col]), out)
            manifest = json.loads((out / "pseudo-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["pseudo"])
            self.assertTrue(all(f["pseudo"] for f in manifest["frames"]))
            self.assertTrue(all(f["file"].startswith("ps_") for f in manifest["frames"]))

    def test_boxes_are_written_back_as_yolo_centre_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp) / "c", [row("a", [box(0.9, x=0.30, y=0.40)])])
            out = Path(tmp) / "out"
            write_yolo(select_frames([col]), out)
            line = next((out / "train" / "labels").iterdir()).read_text(encoding="utf-8").strip()
            cls, cx, cy, w, h = line.split()
            self.assertEqual(cls, "0")
            self.assertAlmostEqual(float(cx), 0.30 + 0.08/2, places=5)
            self.assertAlmostEqual(float(cy), 0.40 + 0.12/2, places=5)


if __name__ == "__main__":
    unittest.main()
