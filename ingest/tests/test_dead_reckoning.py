"""Coasting a track through an occlusion.

The failure guarded against throughout: an invented position that looks like an observation.
Doc 0 forbids interpolating across a gap, and the distinction that makes this legal at all is
detection_lost (camera still there) versus shot_change (camera moved, robot could be anywhere).
"""

import unittest

from ingest.collection.dead_reckoning import (
    MAX_COAST_SECONDS, Sample, coast, estimate_velocity, fill_gap)


def track(n=4, step=0.2, vx=0.05, vy=0.0, x0=0.20, y0=0.50):
    return [Sample(t=i*step, x=x0+vx*i*step, y=y0+vy*i*step, w=0.08, h=0.12) for i in range(n)]


class VelocityTests(unittest.TestCase):
    def test_constant_motion_is_recovered(self):
        vx, vy = estimate_velocity(track(vx=0.05))
        self.assertAlmostEqual(vx, 0.05, places=6)
        self.assertAlmostEqual(vy, 0.0, places=6)

    def test_a_single_observation_yields_no_velocity(self):
        self.assertEqual(estimate_velocity(track(n=1)), (0.0, 0.0))

    def test_estimated_samples_do_not_feed_the_next_estimate(self):
        # Otherwise a coast compounds on itself and drifts on its own output.
        real = track(n=3)
        polluted = real + [Sample(t=1.0, x=0.99, y=0.99, w=0.08, h=0.12, estimated=True)]
        self.assertEqual(estimate_velocity(real), estimate_velocity(polluted))

    def test_one_jittery_box_does_not_set_the_direction(self):
        clean = track(n=6, vx=0.05)
        noisy = list(clean)
        noisy[-1] = Sample(t=noisy[-1].t, x=noisy[-1].x + 0.09, y=noisy[-1].y, w=0.08, h=0.12)
        self.assertLess(abs(estimate_velocity(noisy)[0] - 0.05), 0.09,
                        "a least-squares fit should absorb one bad sample")


class GapReasonTests(unittest.TestCase):
    def test_a_camera_cut_is_never_estimated_across(self):
        self.assertEqual(coast(track(), until=1.5, step=0.2, gap_reason="shot_change"), [])

    def test_an_unknown_reason_is_refused(self):
        self.assertEqual(coast(track(), until=1.5, step=0.2, gap_reason="something_else"), [])

    def test_an_occlusion_is_estimated_across(self):
        self.assertTrue(coast(track(), until=1.0, step=0.2, gap_reason="detection_lost"))


class CoastTests(unittest.TestCase):
    def test_position_continues_along_the_observed_velocity(self):
        got = coast(track(vx=0.05), until=0.8, step=0.2, gap_reason="detection_lost")
        self.assertAlmostEqual(got[0].x, 0.20 + 0.05 * 0.8, places=5)

    def test_every_synthesised_sample_is_marked_estimated(self):
        got = coast(track(), until=1.0, step=0.2, gap_reason="detection_lost")
        self.assertTrue(got and all(s.estimated for s in got))

    def test_confidence_decays_with_time(self):
        got = coast(track(), until=1.0, step=0.2, gap_reason="detection_lost")
        self.assertGreater(got[0].confidence, got[-1].confidence)

    def test_it_stops_at_the_horizon_rather_than_drifting(self):
        got = coast(track(), until=30.0, step=0.2, gap_reason="detection_lost")
        span = got[-1].t - track()[-1].t
        self.assertLessEqual(span, MAX_COAST_SECONDS + 1e-9)

    def test_it_stops_when_the_estimate_leaves_the_frame(self):
        # Coasting a robot off the edge of the image is not a position anyone can use.
        fast = [Sample(t=i*0.2, x=0.90 + 0.20*i*0.2, y=0.5, w=0.05, h=0.05) for i in range(3)]
        got = coast(fast, until=1.0, step=0.2, gap_reason="detection_lost")
        self.assertTrue(all(0.0 <= s.x <= 1.0 for s in got))


class FillTests(unittest.TestCase):
    def test_a_bridged_gap_lands_on_the_next_real_observation(self):
        before = track(n=3, step=0.2, vx=0.05)
        after = [Sample(t=1.0, x=0.60, y=0.50, w=0.08, h=0.12)]
        got = fill_gap(before, after, step=0.2, gap_reason="detection_lost")
        self.assertTrue(got)
        # The last estimate should approach the observation, not the extrapolation.
        self.assertLess(abs(got[-1].x - 0.60), abs(before[-1].x - 0.60))

    def test_filling_is_refused_across_a_camera_cut(self):
        before = track(n=3)
        after = [Sample(t=1.0, x=0.60, y=0.50, w=0.08, h=0.12)]
        self.assertEqual(fill_gap(before, after, 0.2, gap_reason="shot_change"), [])

    def test_a_gap_longer_than_the_horizon_is_not_bridged(self):
        before = track(n=3)
        far = [Sample(t=30.0, x=0.60, y=0.50, w=0.08, h=0.12)]
        got = fill_gap(before, far, 0.2, gap_reason="detection_lost")
        self.assertTrue(all(s.t - before[-1].t <= MAX_COAST_SECONDS + 1e-9 for s in got))

    def test_filled_samples_are_marked_estimated_too(self):
        before = track(n=3)
        after = [Sample(t=1.0, x=0.60, y=0.50, w=0.08, h=0.12)]
        got = fill_gap(before, after, 0.2, gap_reason="detection_lost")
        self.assertTrue(all(s.estimated for s in got))


if __name__ == "__main__":
    unittest.main()
