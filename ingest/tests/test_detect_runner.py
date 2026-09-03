"""The detect-and-fuse pipeline, exercised without a trained model present.

Everything except the model call is tested here with stub detectors, so when real weights arrive
the only untested surface is the ONNX inference itself. Waiting for a model to test the plumbing
is how you discover a path bug at the worst moment.
"""

import json
import tempfile
import unittest
from pathlib import Path

from ingest.collection.detect_runner import (
    fuse_and_write, non_max_suppression, run_detectors, usable_frames)


class StubDetector:
    """Returns fixed boxes, so fusion behaviour is the thing under test, not a model."""

    def __init__(self, name, boxes):
        self.name = name
        self._boxes = boxes
        self.calls = 0

    def detect(self, image_bgr):
        self.calls += 1
        return list(self._boxes)


def _collection(root: Path, frames: list[tuple[str, bool]]) -> Path:
    """Build a collection with (frame_id, quality_ok) pairs and 1px placeholder images."""
    import cv2
    import numpy as np

    (root / "frames").mkdir(parents=True)
    rows = []
    for fid, ok in frames:
        img_rel = f"frames/{fid}.jpg"
        cv2.imwrite(str(root / img_rel), np.full((90, 160, 3), 120, dtype=np.uint8))
        rows.append({"frame_id": fid, "image_path": img_rel, "quality_ok": ok,
                     "quality_reason": "ok" if ok else "graphic_card"})
    (root / "frames.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return root


def box(x, y, c=0.6):
    return {"x": x, "y": y, "w": 0.10, "h": 0.16, "confidence": c}


class NmsTests(unittest.TestCase):
    """Raw YOLO output repeats each object across many anchors.

    Found the hard way: without suppression one robot arrived as seven boxes at the same spot,
    a frame reported 21 detections when the field holds six, and box fusion would have read one
    detector's repeated opinion as corroboration.
    """

    def test_a_cluster_on_one_object_collapses_to_its_best_box(self):
        boxes = [box(0.30 + i * 0.001, 0.40, c=0.5 + i * 0.05) for i in range(7)]
        kept = non_max_suppression(boxes)
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(kept[0]["confidence"], 0.80, places=6)

    def test_genuinely_separate_objects_all_survive(self):
        kept = non_max_suppression([box(0.10, 0.10), box(0.50, 0.50), box(0.85, 0.20)])
        self.assertEqual(len(kept), 3)

    def test_output_is_ordered_by_confidence(self):
        kept = non_max_suppression([box(0.1, 0.1, 0.3), box(0.5, 0.5, 0.9), box(0.85, 0.2, 0.6)])
        self.assertEqual([b["confidence"] for b in kept], [0.9, 0.6, 0.3])

    def test_nothing_in_nothing_out(self):
        self.assertEqual(non_max_suppression([]), [])


class UsableFrameTests(unittest.TestCase):
    def test_rejected_frames_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [("a", True), ("b", False), ("c", True)])
            self.assertEqual([f["frame_id"] for f in usable_frames(col)], ["a", "c"])

    def test_collections_without_the_flag_keep_everything(self):
        # Collections extracted before the quality filter existed have no flag; treating a
        # missing flag as "rejected" would silently discard every older collection.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "frames").mkdir(parents=True)
            (root / "frames.jsonl").write_text(
                json.dumps({"frame_id": "old", "image_path": "frames/old.jpg"}) + "\n",
                encoding="utf-8")
            self.assertEqual(len(usable_frames(root)), 1)


class RunTests(unittest.TestCase):
    def test_detector_never_sees_a_rejected_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [("a", True), ("b", False), ("c", False)])
            d = StubDetector("stub", [box(0.3, 0.4)])
            run_detectors(col, [d])
            self.assertEqual(d.calls, 1, "a rejected frame was sent to the detector")

    def test_every_detector_runs_on_every_usable_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [("a", True), ("b", True)])
            d1 = StubDetector("yolo", [box(0.3, 0.4)])
            d2 = StubDetector("rfdetr", [box(0.3, 0.4)])
            out = run_detectors(col, [d1, d2])
            self.assertEqual(set(out), {"a", "b"})
            self.assertEqual(set(out["a"]), {"yolo", "rfdetr"})


class FuseWriteTests(unittest.TestCase):
    def test_agreement_survives_into_the_written_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [("a", True)])
            per_frame = run_detectors(col, [
                StubDetector("yolo", [box(0.30, 0.40)]),
                StubDetector("rfdetr", [box(0.31, 0.40)]),
            ])
            path = fuse_and_write(col, per_frame)
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

            self.assertEqual(row["detectors"], ["rfdetr", "yolo"])
            self.assertEqual(len(row["boxes"]), 1, "agreeing detectors should collapse to one box")
            self.assertEqual(row["boxes"][0]["agreement_count"], 2)
            self.assertTrue(row["human_review_required"])

    def test_a_lone_confident_box_is_ranked_below_a_corroborated_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [("a", True)])
            per_frame = run_detectors(col, [
                StubDetector("yolo", [box(0.30, 0.40, 0.55), box(0.80, 0.10, 0.99)]),
                StubDetector("rfdetr", [box(0.30, 0.40, 0.55)]),
            ])
            path = fuse_and_write(col, per_frame)
            boxes = json.loads(path.read_text(encoding="utf-8").splitlines()[0])["boxes"]
            self.assertEqual(boxes[0]["agreement_count"], 2)
            self.assertEqual(boxes[-1]["agreement_count"], 1)

    def test_weights_are_estimated_over_the_collection_not_one_frame(self):
        # A single frame cannot show that a detector habitually invents boxes.
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [(f"f{i}", True) for i in range(8)])
            per_frame = run_detectors(col, [
                StubDetector("good", [box(0.30, 0.40)]),
                StubDetector("twin", [box(0.30, 0.40)]),
                StubDetector("noisy", [box(0.90, 0.90)]),
            ])
            path = fuse_and_write(col, per_frame)
            row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            weights = row["source_weights"]
            self.assertLess(weights["noisy"], weights["good"])

    def test_rewriting_replaces_rather_than_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            col = _collection(Path(tmp), [("a", True)])
            per_frame = run_detectors(col, [StubDetector("yolo", [box(0.3, 0.4)])])
            fuse_and_write(col, per_frame)
            path = fuse_and_write(col, per_frame)
            self.assertEqual(len(path.read_text(encoding="utf-8").strip().splitlines()), 1)



class RfDetrDecodeTests(unittest.TestCase):
    """RF-DETR's output format differs from YOLO's; the decode must match the C++ authority.

    The model call is not exercised here (no ONNX in the test env), but the decode contract is:
    dets are cxcywh and must come out as top-left xywh, and the robot class is read through a
    sigmoid. A stub session lets that arithmetic be checked without weights.
    """

    def test_center_form_dets_become_top_left(self):
        import numpy as np
        from ingest.collection.detect_runner import RfDetrDetector

        d = RfDetrDetector.__new__(RfDetrDetector)
        d.name, d.confidence_threshold, d.input_size = "rfdetr", 0.25, 640
        d.robot_class_id, d.nms_iou = 0, 0.5

        class Stub:
            def get_inputs(self):
                class I: name = "input"
                return [I()]
            def run(self, _out, _feed):
                # one query: centre (0.5,0.5) size (0.2,0.4); robot logit high, other low
                dets = np.array([[[0.5, 0.5, 0.2, 0.4]]], np.float32)
                labels = np.array([[[3.0, -5.0]]], np.float32)
                return [dets, labels]
        d._session = Stub()

        boxes = d.detect(np.zeros((720, 1280, 3), np.uint8))
        self.assertEqual(len(boxes), 1)
        b = boxes[0]
        self.assertAlmostEqual(b["x"], 0.4, places=5)   # 0.5 - 0.2/2
        self.assertAlmostEqual(b["y"], 0.3, places=5)   # 0.5 - 0.4/2
        self.assertGreater(b["confidence"], 0.9)         # sigmoid(3.0)

    def test_the_dead_class_is_not_reported(self):
        import numpy as np
        from ingest.collection.detect_runner import RfDetrDetector
        d = RfDetrDetector.__new__(RfDetrDetector)
        d.name, d.confidence_threshold, d.input_size = "rfdetr", 0.25, 640
        d.robot_class_id, d.nms_iou = 0, 0.5

        class Stub:
            def get_inputs(self):
                class I: name = "input"
                return [I()]
            def run(self, _o, _f):
                return [np.array([[[0.5,0.5,0.2,0.2]]],np.float32),
                        np.array([[[-6.0, 4.0]]],np.float32)]   # robot class low
        d._session = Stub()
        self.assertEqual(d.detect(np.zeros((720,1280,3),np.uint8)), [])



if __name__ == "__main__":
    unittest.main()
