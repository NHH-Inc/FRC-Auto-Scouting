"""The dense labelling pass, exercised with stub detectors and synthetic frames.

Video I/O is isolated in sample_and_label; everything decided here -- graphic rejection,
temporal fusion, honest marking -- is tested against label_sequence without opening a file.
"""

import unittest

import numpy as np

from ingest.collection.dense_label import DenseStats, label_sequence


class StubDetector:
    def __init__(self, per_frame_boxes):
        self._boxes = per_frame_boxes
        self._i = 0

    def detect(self, image):
        boxes = self._boxes[self._i]
        self._i += 1
        return list(boxes)


def box(x, y, w=0.06, h=0.10, c=0.6):
    return {"x": x, "y": y, "w": w, "h": h, "confidence": c}


def gameplay_frame():
    # Mid-brightness varied content, like a real arena shot: brightness ~110-135 (below the
    # graphic cutoff), low flat-share, real contrast. Pure 0-255 noise is wrong here -- its
    # per-pixel channel max averages ~190 and trips the overbright rule.
    return np.random.default_rng(0).integers(50, 150, (180, 320, 3), dtype=np.uint8)


def graphic_frame():
    # A near-uniform bright fill trips the graphic_card rule.
    return np.full((180, 320, 3), 200, dtype=np.uint8)


class LabelSequenceTests(unittest.TestCase):
    def test_a_persistent_robot_is_corroborated(self):
        frames = [gameplay_frame() for _ in range(5)]
        times = [i * 0.2 for i in range(5)]
        moving = [[box(0.20 + 0.01 * i, 0.5)] for i in range(5)]
        stats = DenseStats()

        rows = label_sequence(frames, times, StubDetector(moving), stats)

        self.assertEqual(len(rows), 5)
        self.assertGreater(stats.corroborated, 0, "a box present every frame should be corroborated")
        self.assertTrue(rows[2]["boxes"][0]["agreement_count"] >= 2)

    def test_a_one_frame_flicker_is_not_corroborated(self):
        frames = [gameplay_frame() for _ in range(5)]
        times = [i * 0.2 for i in range(5)]
        detections = [[box(0.2 + 0.01 * i, 0.5)] for i in range(5)]
        detections[2].append(box(0.90, 0.10, c=0.95))     # confident, single-frame
        stats = DenseStats()

        rows = label_sequence(frames, times, StubDetector(detections), stats)

        flickers = [b for b in rows[2]["boxes"] if abs(b["x"] - 0.90) < 0.02]
        if flickers:
            self.assertEqual(flickers[0]["agreement_count"], 1)
            self.assertLess(flickers[0]["confidence"], 0.6)

    def test_a_graphic_frame_is_never_sent_to_the_detector(self):
        frames = [gameplay_frame(), graphic_frame(), gameplay_frame()]
        times = [0.0, 0.2, 0.4]
        # Detector would only be called for the two gameplay frames.
        stub = StubDetector([[box(0.2, 0.5)], [box(0.2, 0.5)]])
        stats = DenseStats()

        rows = label_sequence(frames, times, stub, stats)

        self.assertEqual(len(rows), 3, "a rejected frame still produces a row, to keep time aligned")
        self.assertEqual(rows[1]["boxes"], [], "the graphic frame carries no boxes")
        self.assertEqual(stats.frames_graphic, 1)

    def test_every_row_is_marked_as_proposal(self):
        frames = [gameplay_frame() for _ in range(3)]
        rows = label_sequence(frames, [0, 0.2, 0.4],
                              StubDetector([[box(0.2, 0.5)]] * 3), DenseStats())
        for row in rows:
            self.assertEqual(row["status"], "proposed")
            self.assertTrue(row["human_review_required"])

    def test_timestamps_are_preserved(self):
        frames = [gameplay_frame() for _ in range(3)]
        rows = label_sequence(frames, [0.0, 0.2, 0.4],
                              StubDetector([[]] * 3), DenseStats())
        self.assertEqual([r["t_seconds"] for r in rows], [0.0, 0.2, 0.4])


if __name__ == "__main__":
    unittest.main()
