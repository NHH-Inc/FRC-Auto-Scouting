"""Rules that decide whether an auto-calibration may be trusted.

Every one of these guards a failure that produces confident nonsense rather than an error: a
homography fitted to a moving camera, to two cameras at once, or to tags at different heights
reports wrong field positions forever and never says so.
"""

from ingest.collection.calibrate import TagSighting, steady_tags


def sighting(tag_id, points):
    s = TagSighting(tag_id)
    for x, y in points:
        s.xs.append(x)
        s.ys.append(y)
    return s


class TestDrift:
    def test_a_static_camera_gives_almost_no_drift(self):
        # Real numbers from a real match: every usable tag came in under one pixel across 40
        # frames spanning the whole clip.
        s = sighting(2, [(597.7, 439.7), (597.9, 439.5), (597.5, 440.0), (598.0, 439.6)])
        assert s.drift() < 1.0

    def test_a_panning_camera_shows_up_as_drift(self):
        s = sighting(2, [(100.0, 400.0), (140.0, 402.0), (180.0, 404.0)])
        assert s.drift() > 12.0

    def test_the_median_resists_a_single_bad_detection(self):
        # One frame where the detector latched onto something else must not drag the point.
        s = sighting(2, [(600.0, 440.0), (601.0, 440.0), (599.0, 440.0), (1500.0, 900.0)])
        x, y = s.median()
        assert 599.0 <= x <= 601.0
        assert y == 440.0

    def test_one_sighting_has_no_drift_to_measure(self):
        assert sighting(2, [(10.0, 10.0)]).drift() == 0.0


class TestSteadyTags:
    def test_still_tags_are_kept(self):
        tags = {2: sighting(2, [(600.0, 440.0)] * 5)}
        kept, notes = steady_tags(tags)
        assert kept == {2: (600.0, 440.0)}
        assert notes == []

    def test_a_moving_tag_is_dropped_and_the_reason_recorded(self):
        # Silently averaging this would invent a point the camera never saw. The reason has to
        # reach the operator, because "camera is not static" changes what they should do next.
        tags = {2: sighting(2, [(100.0, 400.0), (300.0, 400.0), (500.0, 400.0)])}
        kept, notes = steady_tags(tags)
        assert kept == {}
        assert any("not static" in n for n in notes)

    def test_a_tag_seen_once_or_twice_is_a_coincidence(self):
        tags = {7: sighting(7, [(600.0, 440.0), (600.0, 440.0)])}
        kept, notes = steady_tags(tags)
        assert kept == {}
        assert any("sightings" in n for n in notes)

    def test_good_and_bad_tags_are_separated_not_all_or_nothing(self):
        tags = {
            2: sighting(2, [(600.0, 440.0)] * 5),
            9: sighting(9, [(100.0, 400.0), (400.0, 400.0), (800.0, 400.0)]),
        }
        kept, notes = steady_tags(tags)
        assert set(kept) == {2}
        assert len(notes) == 1

    def test_nothing_seen_is_not_a_crash(self):
        assert steady_tags({}) == ({}, [])
