"""Exporting machine labels into training data, and the rule that stops it going backwards.

The completeness check is the load-bearing test here. Everything else is bookkeeping; that one
decides whether the second generation of the model is better or quietly worse than the first.
"""

import unittest

from ingest.collection.dense_to_dataset import (
    DOUBT_FLOOR, MAX_BOXES_PER_FRAME, MIN_CONFIDENCE, Selection, cap_against_human, keep_box,
    labels_look_complete)


def box(conf, agreement=2, x=0.3, y=0.4):
    return {"x": x, "y": y, "w": 0.08, "h": 0.12,
            "confidence": conf, "agreement_count": agreement}


class KeepBoxTests(unittest.TestCase):
    def test_a_corroborated_confident_box_is_kept(self):
        ok, _ = keep_box(box(0.9))
        self.assertTrue(ok)

    def test_an_uncorroborated_box_is_refused_however_confident(self):
        ok, why = keep_box(box(0.99, agreement=1))
        self.assertFalse(ok)
        self.assertEqual(why, "uncorroborated")

    def test_a_weak_box_is_refused_however_corroborated(self):
        ok, why = keep_box(box(0.1, agreement=3))
        self.assertFalse(ok)
        self.assertEqual(why, "low_confidence")


class CompletenessTests(unittest.TestCase):
    """A detector treats unlabelled pixels as background, so a partly-labelled frame is poison."""

    def test_a_frame_with_no_doubt_is_usable(self):
        # Everything is either clearly a robot or clearly nothing.
        self.assertTrue(labels_look_complete([box(0.9), box(0.8), box(0.05)]))

    def test_a_candidate_in_the_doubt_band_disqualifies_the_frame(self):
        # 0.45 is too weak to label but too strong to call background: there is probably a robot
        # here we are about to teach as empty carpet.
        mid = (DOUBT_FLOOR + MIN_CONFIDENCE) / 2
        self.assertFalse(labels_look_complete([box(0.9), box(mid)]))

    def test_an_uncorroborated_candidate_also_disqualifies_it(self):
        # Temporal persistence did not back it, but the detector still saw something.
        self.assertFalse(labels_look_complete([box(0.9), box(0.7, agreement=1)]))

    def test_a_genuinely_empty_frame_is_usable(self):
        self.assertTrue(labels_look_complete([]))

    def test_noise_far_below_the_doubt_floor_does_not_disqualify(self):
        # Every detector emits a long tail of near-zero scores; treating those as doubt would
        # reject every frame in the dataset.
        self.assertTrue(labels_look_complete([box(0.9), box(DOUBT_FLOOR - 0.05)]))

    def test_a_close_up_with_two_confident_robots_is_usable(self):
        # The failure this whole rule guards against is confusing "only two robots visible" with
        # "four robots missed". No doubt present means the former.
        self.assertTrue(labels_look_complete([box(0.85), box(0.77)]))


class CapTests(unittest.TestCase):
    def _sel(self, n):
        return [Selection(f"m{i}", "v.mp4", float(i), [box(0.9)]) for i in range(n)]

    def test_machine_labels_stay_a_minority_of_train(self):
        capped = cap_against_human(self._sel(10_000), human_train_count=1000, ratio=0.5)
        self.assertEqual(len(capped), 1000)

    def test_a_small_selection_is_left_alone(self):
        self.assertEqual(len(cap_against_human(self._sel(50), 1000, 0.5)), 50)

    def test_trimming_spreads_rather_than_truncates(self):
        # Truncating would drop whole matches from the end of the alphabet.
        capped = cap_against_human(self._sel(1000), human_train_count=100, ratio=0.5)
        ids = [s.match_id for s in capped]
        self.assertNotEqual(ids, [f"m{i}" for i in range(len(ids))],
                            "an evenly spaced sample should not be the first N")
        self.assertEqual(len(set(ids)), len(ids))


if __name__ == "__main__":
    unittest.main()
