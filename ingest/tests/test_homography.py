"""Image-to-field mapping.

Tested against synthetic geometry where the correct answer is known exactly, because a wrong
homography does not raise -- it returns confident, wrong distances, and every speed and position
computed from it inherits the error silently.
"""

import math
import unittest

from ingest.collection.homography import (
    MAX_PLAUSIBLE_FTPS,
    Homography,
    implausible,
    solve,
    speed_ftps,
)

LENGTH, WIDTH = 54.0, 26.6

# A camera looking straight down at the field: image maps to field by a pure scale. The correct
# answer is therefore known for every point, not just the four fitted ones.
TOP_DOWN_IMAGE = [(0.0, 0.0), (1920.0, 0.0), (1920.0, 1080.0), (0.0, 1080.0)]
TOP_DOWN_FIELD = [(0.0, 0.0), (LENGTH, 0.0), (LENGTH, WIDTH), (0.0, WIDTH)]


def top_down() -> Homography:
    h = solve(TOP_DOWN_IMAGE, TOP_DOWN_FIELD, LENGTH, WIDTH)
    assert h is not None
    return h


class SolveTests(unittest.TestCase):
    def test_a_known_mapping_is_recovered_exactly(self):
        h = top_down()
        self.assertLess(h.reprojection_ft, 0.01)
        self.assertTrue(h.trustworthy)

    def test_it_maps_points_it_was_never_fitted_on(self):
        # Fitting four corners is easy; the test is the middle of the image.
        h = top_down()
        fx, fy = h.to_field(960.0, 540.0)
        self.assertAlmostEqual(fx, LENGTH / 2, places=3)
        self.assertAlmostEqual(fy, WIDTH / 2, places=3)

    def test_fewer_than_four_points_is_refused(self):
        self.assertIsNone(solve(TOP_DOWN_IMAGE[:3], TOP_DOWN_FIELD[:3], LENGTH, WIDTH))

    def test_mismatched_point_counts_are_refused(self):
        self.assertIsNone(solve(TOP_DOWN_IMAGE, TOP_DOWN_FIELD[:3], LENGTH, WIDTH))

    def test_collinear_points_do_not_produce_a_confident_answer(self):
        # Four points on a line describe no plane. The danger is returning something anyway.
        line_img = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0), (300.0, 0.0)]
        line_field = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (15.0, 0.0)]
        result = solve(line_img, line_field, LENGTH, WIDTH)
        self.assertTrue(result is None or not result.trustworthy)

    def test_four_points_cannot_detect_their_own_error(self):
        # Four correspondences determine a homography exactly, so even a corner misplaced by 25
        # feet reprojects with zero residual. This is a property of the maths, and the danger is
        # mistaking that zero for confirmation.
        bad = list(TOP_DOWN_FIELD)
        bad[2] = (LENGTH, WIDTH + 25.0)
        h = solve(TOP_DOWN_IMAGE, bad, LENGTH, WIDTH)
        self.assertIsNotNone(h)
        self.assertLess(h.reprojection_ft, 0.01, "4 points always fit exactly")
        self.assertFalse(h.has_redundancy, "and the caller must be told the error proves nothing")

    def test_a_bad_correspondence_is_caught_once_there_is_redundancy(self):
        # A fifth point gives the bad one something to disagree with.
        img = TOP_DOWN_IMAGE + [(960.0, 540.0)]
        field = list(TOP_DOWN_FIELD) + [(LENGTH / 2, WIDTH / 2 + 20.0)]   # misplaced by 20 ft
        h = solve(img, field, LENGTH, WIDTH)
        self.assertIsNotNone(h)
        self.assertTrue(h.has_redundancy)
        self.assertFalse(h.trustworthy, "an overdetermined fit must expose the bad point")


class BoxTests(unittest.TestCase):
    def test_a_box_maps_from_its_bottom_edge_not_its_centre(self):
        # A robot stands on the carpet, and the carpet is the plane being modelled. Using the box
        # centre places it metres behind where it actually is.
        h = top_down()
        centre = h.to_field(0.5 * 1920, 0.5 * 1080)
        bottom = h.box_to_field(0.45, 0.40, 0.10, 0.20, 1920, 1080)   # bottom edge at 0.60
        self.assertAlmostEqual(bottom[0], centre[0], places=3)
        self.assertGreater(bottom[1], centre[1], "bottom edge should map further down the field")

    def test_points_inside_the_field_are_on_field(self):
        h = top_down()
        self.assertTrue(h.on_field(960.0, 540.0))

    def test_points_far_outside_the_field_are_rejected(self):
        h = top_down()
        self.assertFalse(h.on_field(-9000.0, 540.0))

    def test_the_margin_tolerates_the_field_edge(self):
        # Bumpers overhang and the camera sees past the guardrail; the very edge is legitimate.
        h = top_down()
        self.assertTrue(h.on_field(0.0, 0.0))
        self.assertTrue(h.on_field(1919.0, 1079.0))


class SpeedTests(unittest.TestCase):
    def test_speed_is_distance_over_time_in_feet(self):
        self.assertAlmostEqual(speed_ftps((0.0, 0.0), 0.0, (3.0, 4.0), 1.0), 5.0, places=6)

    def test_half_the_time_is_twice_the_speed(self):
        self.assertAlmostEqual(speed_ftps((0.0, 0.0), 0.0, (3.0, 4.0), 0.5), 10.0, places=6)

    def test_equal_timestamps_return_none_rather_than_infinity(self):
        # inf propagates into every aggregate downstream and is hard to trace back.
        self.assertIsNone(speed_ftps((0.0, 0.0), 1.0, (3.0, 4.0), 1.0))

    def test_time_running_backwards_returns_none(self):
        self.assertIsNone(speed_ftps((0.0, 0.0), 2.0, (3.0, 4.0), 1.0))

    def test_a_nan_position_does_not_produce_a_number(self):
        self.assertIsNone(speed_ftps((math.nan, 0.0), 0.0, (3.0, 4.0), 1.0))

    def test_impossible_speeds_are_flagged(self):
        # Nothing on an FRC field outruns its drivetrain. This is an identity-swap detector.
        self.assertTrue(implausible(MAX_PLAUSIBLE_FTPS + 5))
        self.assertFalse(implausible(12.0))
        self.assertFalse(implausible(None))


if __name__ == "__main__":
    unittest.main()
