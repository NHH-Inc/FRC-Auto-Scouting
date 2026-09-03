"""The official 2026 AprilTag layout, and the coplanarity trap it contains.

These run against the real vendored file, not a fixture. A test that passes on invented tag
coordinates would prove nothing about the thing we actually depend on.
"""

import unittest
from pathlib import Path

from ingest.collection.apriltag_layout import (
    METRES_TO_FEET, correspondences_from_observations, load_layout)

LAYOUT = Path("contracts/fields/2026-apriltags.json")


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.layout = load_layout(LAYOUT)

    def test_it_is_the_2026_rebuilt_layout(self):
        self.assertEqual(self.layout.season, 2026)
        self.assertIn("Rebuilt", self.layout.name)

    def test_all_thirty_two_tags_load(self):
        self.assertEqual(len(self.layout.tags), 32)

    def test_metres_are_converted_to_feet(self):
        # Tag 1 is published at x = 11.8779798 m.
        self.assertAlmostEqual(self.layout.tags[1].x_ft, 11.8779798 * METRES_TO_FEET, places=6)

    def test_field_dimensions_match_the_published_size(self):
        self.assertAlmostEqual(self.layout.length_ft, 16.541 * METRES_TO_FEET, places=3)
        self.assertAlmostEqual(self.layout.width_ft, 8.069 * METRES_TO_FEET, places=3)

    def test_every_tag_sits_inside_the_field(self):
        for tag in self.layout.tags.values():
            self.assertGreaterEqual(tag.x_ft, -1.0)
            self.assertLessEqual(tag.x_ft, self.layout.length_ft + 1.0)
            self.assertGreaterEqual(tag.y_ft, -1.0)
            self.assertLessEqual(tag.y_ft, self.layout.width_ft + 1.0)


class CoplanarityTests(unittest.TestCase):
    """The reason this module exists rather than feeding tags straight to findHomography."""

    def setUp(self):
        self.layout = load_layout(LAYOUT)

    def test_the_tags_are_not_all_at_one_height(self):
        self.assertGreater(len(self.layout.height_groups()), 1,
                           "if this ever becomes 1, the coplanar handling can be simplified")

    def test_the_largest_coplanar_group_is_the_sixteen_at_the_top_height(self):
        group = self.layout.largest_coplanar_group()
        self.assertEqual(len(group), 16)
        self.assertEqual(len({t.height_key for t in group}), 1)

    def test_the_group_is_ordered_so_calibration_is_reproducible(self):
        ids = [t.id for t in self.layout.largest_coplanar_group()]
        self.assertEqual(ids, sorted(ids))


class CorrespondenceTests(unittest.TestCase):
    def setUp(self):
        self.layout = load_layout(LAYOUT)

    def test_observations_pair_with_surveyed_positions(self):
        group = self.layout.largest_coplanar_group()[:5]
        observed = {t.id: (100.0 + i * 50, 200.0) for i, t in enumerate(group)}
        pairs = correspondences_from_observations(self.layout, observed)
        self.assertEqual(len(pairs), 5)
        image, field = pairs[0]
        self.assertEqual(image, observed[group[0].id])
        self.assertAlmostEqual(field[0], group[0].x_ft, places=6)

    def test_mixed_heights_are_reduced_to_one_plane_by_default(self):
        # The silent failure this prevents: a fit through points that share no plane.
        groups = self.layout.height_groups()
        tall = sorted(groups[max(groups, key=lambda k: len(groups[k]))], key=lambda t: t.id)
        short = sorted(groups[min(groups)], key=lambda t: t.id)
        observed = {t.id: (10.0, 10.0) for t in tall[:6]}
        observed.update({t.id: (20.0, 20.0) for t in short[:3]})

        pairs = correspondences_from_observations(self.layout, observed)
        self.assertEqual(len(pairs), 6, "only the dominant height should survive")

    def test_the_restriction_can_be_lifted_for_a_pnp_solve(self):
        groups = self.layout.height_groups()
        tall = sorted(groups[max(groups, key=lambda k: len(groups[k]))], key=lambda t: t.id)
        short = sorted(groups[min(groups)], key=lambda t: t.id)
        observed = {t.id: (10.0, 10.0) for t in tall[:6]}
        observed.update({t.id: (20.0, 20.0) for t in short[:3]})

        pairs = correspondences_from_observations(self.layout, observed, require_coplanar=False)
        self.assertEqual(len(pairs), 9)

    def test_unknown_tag_ids_are_ignored_not_guessed(self):
        pairs = correspondences_from_observations(self.layout, {9999: (10.0, 10.0)})
        self.assertEqual(pairs, [])


if __name__ == "__main__":
    unittest.main()
