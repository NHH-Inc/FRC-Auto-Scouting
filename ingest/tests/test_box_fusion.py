"""Box fusion: does a confidence actually shift according to what everything else said?

The behaviour under test is the one that was asked for -- a lone confident box should lose to a
corroborated hesitant one -- so these assert the ORDERING that produces, not just that numbers
come out.
"""

import unittest

from ingest.collection.box_fusion import (
    FusedBox,
    estimate_source_weights,
    fuse_frame,
    iou,
)


def box(x, y, w=0.10, h=0.16, confidence=0.5):
    return {"x": x, "y": y, "w": w, "h": h, "confidence": confidence}


class IoUTests(unittest.TestCase):
    def test_identical_boxes_overlap_completely(self):
        self.assertAlmostEqual(iou(box(0.2, 0.2), box(0.2, 0.2)), 1.0)

    def test_disjoint_boxes_do_not_overlap(self):
        self.assertEqual(iou(box(0.0, 0.0), box(0.8, 0.8)), 0.0)


class FusionTests(unittest.TestCase):
    def test_agreeing_sources_collapse_to_one_box(self):
        fused = fuse_frame({
            "a": [box(0.30, 0.40)],
            "b": [box(0.31, 0.40)],
            "c": [box(0.30, 0.41)],
        })
        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0].supporting_sources, ["a", "b", "c"])

    def test_a_corroborated_weak_box_outranks_a_lone_confident_one(self):
        # The whole point. One source screaming 0.95 about a box nobody else saw should not
        # outrank three sources quietly agreeing at 0.55.
        fused = fuse_frame({
            "a": [box(0.30, 0.40, confidence=0.55), box(0.80, 0.10, confidence=0.95)],
            "b": [box(0.30, 0.40, confidence=0.55)],
            "c": [box(0.31, 0.40, confidence=0.55)],
        })
        best = fused[0]
        self.assertEqual(len(best.supporting_sources), 3)
        lone = [f for f in fused if len(f.supporting_sources) == 1][0]
        self.assertGreater(best.confidence, lone.confidence)

    def test_one_source_cannot_corroborate_itself(self):
        # Two boxes from the same detector are two objects to that detector. Letting both join a
        # cluster would manufacture agreement out of a single opinion.
        fused = fuse_frame({"a": [box(0.30, 0.40), box(0.305, 0.40)]})
        self.assertEqual(len(fused), 2)
        for f in fused:
            self.assertEqual(f.supporting_sources, ["a"])

    def test_loose_agreement_scores_below_tight_agreement(self):
        tight = fuse_frame({"a": [box(0.30, 0.40)], "b": [box(0.302, 0.40)]})[0]
        loose = fuse_frame({"a": [box(0.30, 0.40)], "b": [box(0.35, 0.45)]})[0]
        self.assertGreater(tight.tightness, loose.tightness)
        self.assertGreater(tight.confidence, loose.confidence)

    def test_fused_position_is_pulled_toward_the_confident_source(self):
        fused = fuse_frame({
            "sure":   [box(0.30, 0.40, confidence=0.9)],
            "unsure": [box(0.34, 0.40, confidence=0.1)],
        })[0]
        self.assertLess(fused.x, 0.32, "should sit nearer the confident box than the midpoint")

    def test_distrusted_source_drags_its_lone_boxes_down(self):
        weights = {"good": 1.9, "noisy": 0.1}
        fused = fuse_frame({
            "good":  [box(0.30, 0.40, confidence=0.6)],
            "noisy": [box(0.80, 0.10, confidence=0.99)],
        }, source_weights=weights)
        by_source = {f.supporting_sources[0]: f for f in fused}
        self.assertGreater(by_source["good"].confidence, by_source["noisy"].confidence)

    def test_every_box_reports_why_it_scored_what_it_did(self):
        fused = fuse_frame({"a": [box(0.3, 0.4)], "b": [box(0.3, 0.4)]})[0].as_dict()
        for key in ("agreement", "tightness", "strength", "source_confidences"):
            self.assertIn(key, fused, "a score that cannot be explained cannot be debugged")


class SourceWeightTests(unittest.TestCase):
    def test_a_source_nobody_corroborates_is_demoted(self):
        frames = [
            {"good": [box(0.3, 0.4)], "twin": [box(0.3, 0.4)], "noisy": [box(0.9, 0.9)]}
            for _ in range(5)
        ]
        weights = estimate_source_weights(frames)
        self.assertLess(weights["noisy"], weights["good"])

    def test_demotion_never_silences_a_source(self):
        frames = [{"good": [box(0.3, 0.4)], "twin": [box(0.3, 0.4)], "noisy": [box(0.9, 0.9)]}]
        self.assertGreater(estimate_source_weights(frames)["noisy"], 0.0)

    def test_weights_average_to_one(self):
        frames = [{"a": [box(0.3, 0.4)], "b": [box(0.3, 0.4)]}]
        weights = estimate_source_weights(frames)
        self.assertAlmostEqual(sum(weights.values()) / len(weights), 1.0, places=6)

    def test_no_frames_yields_no_weights(self):
        self.assertEqual(estimate_source_weights([]), {})


if __name__ == "__main__":
    unittest.main()
