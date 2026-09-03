"""Temporal corroboration: does a box that persists get trusted, and a flicker get cut?

The whole point is separating a real robot (seen across frames) from a one-frame hallucination.
Every test is a version of that distinction. Pure logic, no video -- the sampling is elsewhere.
"""

import unittest

from ingest.collection.temporal_consistency import (
    MIN_PERSISTENT_FRAMES, annotate, confirmed_boxes, link_tracks)


def box(x, y, w=0.08, h=0.12, c=0.6):
    return {"x": x, "y": y, "w": w, "h": h, "confidence": c}


def moving(n, x0=0.20, dx=0.01, y=0.50):
    """A robot crossing the field: one box per frame, drifting steadily."""
    return [[box(x0 + dx * i, y)] for i in range(n)]


class LinkingTests(unittest.TestCase):
    def test_a_steadily_moving_box_forms_one_track(self):
        tracks = link_tracks(moving(6))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].frame_span, 6)

    def test_two_separated_robots_form_two_tracks(self):
        frames = [[box(0.2, 0.3), box(0.8, 0.7)] for _ in range(5)]
        self.assertEqual(len(link_tracks(frames)), 2)

    def test_a_one_frame_blip_is_its_own_short_track(self):
        frames = moving(5)
        frames[2].append(box(0.90, 0.10))    # a hallucination in one frame only
        tracks = link_tracks(frames)
        blips = [t for t in tracks if t.frame_span == 1]
        self.assertEqual(len(blips), 1)

    def test_a_track_survives_a_brief_miss(self):
        frames = moving(5)
        frames[2] = []                        # robot occluded for one frame
        tracks = link_tracks(frames)
        self.assertEqual(len(tracks), 1, "a one-frame gap must not sever the track")
        self.assertEqual(tracks[0].frame_span, 5)

    def test_a_long_gap_ends_the_track(self):
        frames = moving(3) + [[], [], []] + moving(3, x0=0.60)
        tracks = link_tracks(frames)
        self.assertGreaterEqual(len(tracks), 2, "a robot gone for three frames starts a new track")


class PersistenceTests(unittest.TestCase):
    def test_the_span_counts_across_a_survived_gap(self):
        frames = moving(4)
        frames[1] = []
        track = link_tracks(frames)[0]
        # seen at 0,_,2,3 -> span 4, not the 3 hits
        self.assertEqual(track.frame_span, 4)

    def test_short_tracks_are_not_persistent(self):
        tracks = link_tracks(moving(MIN_PERSISTENT_FRAMES - 1))
        self.assertFalse(any(t.persistent for t in tracks))

    def test_long_tracks_are_persistent(self):
        tracks = link_tracks(moving(MIN_PERSISTENT_FRAMES + 2))
        self.assertTrue(all(t.persistent for t in tracks))


class AnnotateTests(unittest.TestCase):
    def test_a_persistent_box_keeps_its_confidence(self):
        out = annotate(moving(6))
        b = out[3][0]
        self.assertEqual(b["temporal_persistence"], 1.0)
        self.assertAlmostEqual(b["confidence"], b["raw_confidence"], places=6)
        self.assertTrue(b["temporally_confirmed"])

    def test_a_flicker_is_cut_hard(self):
        frames = moving(6)
        frames[2].append(box(0.90, 0.10, c=0.95))   # confident but one-frame
        out = annotate(frames)
        flicker = [b for b in out[2] if b["x"] == 0.90][0]
        self.assertLess(flicker["confidence"], 0.5, "a one-frame box must lose most of its score")
        self.assertFalse(flicker["temporally_confirmed"])

    def test_the_raw_confidence_is_preserved_for_audit(self):
        frames = moving(6)
        frames[0].append(box(0.90, 0.10, c=0.88))
        out = annotate(frames)
        blip = [b for b in out[0] if b["x"] == 0.90][0]
        self.assertEqual(blip["raw_confidence"], 0.88, "the original score must survive the reweight")

    def test_persistence_saturates_rather_than_inflating(self):
        # A robot standing still for a long time is not arbitrarily more real than one confirmed
        # over the minimum span.
        short = annotate(moving(MIN_PERSISTENT_FRAMES))[0][0]["temporal_persistence"]
        long = annotate(moving(MIN_PERSISTENT_FRAMES * 20))[0][0]["temporal_persistence"]
        self.assertEqual(short, 1.0)
        self.assertEqual(long, 1.0)


class ConfirmedTests(unittest.TestCase):
    def test_only_persistent_detections_survive(self):
        frames = moving(6)
        frames[3].append(box(0.90, 0.10))
        confirmed = confirmed_boxes(frames)
        # the hallucination is gone; the real robot remains in every frame
        self.assertTrue(all(len(f) == 1 for f in confirmed))
        self.assertFalse(any(b["x"] == 0.90 for f in confirmed for b in f))


if __name__ == "__main__":
    unittest.main()
