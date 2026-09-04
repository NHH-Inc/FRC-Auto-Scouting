"""Deriving events from the clock, from track geometry, and from the scoreboard.

The failure that matters here is inventing an event that did not happen. A fabricated shot or a
phantom immobility becomes a per-team number on a spreadsheet, and nothing downstream can tell it
apart from a real one.
"""

from ingest.action_extraction import (
    immobile_spans,
    immobility_events,
    phase_changes,
    phase_for,
    scoring_moments,
    shots_from_points,
    stable_scores,
    to_events,
)

CONFIG = {"auto_seconds": 15, "teleop_seconds": 135, "endgame_seconds": 20,
          "point_values": {"auto": {"shot_made_high": 0}, "teleop": {"shot_made_high": 0}}}
REAL_2026 = CONFIG          # every point value in the shipped config is a zero placeholder


class TestPhase:
    def test_the_boundaries_are_where_the_config_says(self):
        assert phase_for(0.0, 15, 135, 20) == "auto"
        assert phase_for(14.9, 15, 135, 20) == "auto"
        assert phase_for(15.0, 15, 135, 20) == "teleop"
        assert phase_for(129.9, 15, 135, 20) == "teleop"

    def test_endgame_is_the_tail_of_teleop_not_a_fourth_period(self):
        # 15 + 135 = 150 total, last 20 seconds are endgame, so 130..150.
        assert phase_for(130.0, 15, 135, 20) == "endgame"
        assert phase_for(149.9, 15, 135, 20) == "endgame"

    def test_after_the_match_is_unknown_not_endgame(self):
        # Broadcast clips run past the buzzer. Calling that endgame would attribute post-match
        # milling about to the most decision-relevant phase of the game.
        assert phase_for(200.0, 15, 135, 20) == "unknown"

    def test_two_changes_for_a_full_match(self):
        events = phase_changes(215.0, CONFIG)
        assert [e["phase"] for e in events] == ["teleop", "endgame"]
        assert [e["t_seconds"] for e in events] == [15.0, 130.0]
        assert all(e["confidence"] == 1.0 for e in events)

    def test_a_clip_that_ends_early_gets_only_the_boundaries_it_reached(self):
        assert [e["phase"] for e in phase_changes(20.0, CONFIG)] == ["teleop"]

    def test_a_config_without_a_clock_produces_nothing(self):
        assert phase_changes(215.0, {}) == []


def boxes(points):
    return [{"t": t, "x": x, "y": y, "w": 0.03, "h": 0.05} for t, x, y in points]


class TestImmobility:
    def test_a_parked_robot_is_one_span(self):
        track = boxes([(t, 0.500, 0.500) for t in range(0, 11)])
        spans = immobile_spans(track)
        assert len(spans) == 1
        assert spans[0].start == 0 and spans[0].end == 10

    def test_detector_jitter_is_not_movement(self):
        # A parked robot's box wobbles a pixel or two every frame; that must not end the span.
        track = boxes([(t, 0.500 + 0.001 * (t % 2), 0.500) for t in range(0, 11)])
        assert len(immobile_spans(track)) == 1

    def test_a_moving_robot_is_never_immobile(self):
        track = boxes([(t, 0.10 + 0.05 * t, 0.5) for t in range(0, 11)])
        assert immobile_spans(track) == []

    def test_a_brief_pause_is_normal_play(self):
        # Lining up a shot is not a dead robot, and reporting it as one would make every robot
        # look unreliable.
        track = boxes([(0, 0.5, 0.5), (1, 0.5, 0.5), (2, 0.5, 0.5),
                       (3, 0.9, 0.5), (4, 0.95, 0.5)])
        assert immobile_spans(track) == []

    def test_a_slow_drift_across_the_field_is_not_stationary(self):
        # Each step is inside the radius but the robot crosses the field. Anchoring on the span's
        # start rather than its neighbour is what catches this.
        track = boxes([(t, 0.10 + 0.005 * t, 0.5) for t in range(0, 40)])
        spans = immobile_spans(track)
        assert all(s.end - s.start < 10 for s in spans)

    def test_start_and_end_come_in_pairs_carrying_the_track(self):
        track = {"track_id": 7, "team": 8242,
                 "boxes": boxes([(t, 0.5, 0.5) for t in range(0, 11)])}
        events = immobility_events(track, CONFIG)
        assert [e["event_type"] for e in events] == ["immobile_start", "immobile_end"]
        assert all(e["track_id"] == 7 and e["team"] == 8242 for e in events)

    def test_an_unattributed_track_still_produces_events(self):
        # Attributing the track later moves its events onto a team in one action, so the events
        # must exist first.
        track = {"track_id": 3, "team": None,
                 "boxes": boxes([(t, 0.5, 0.5) for t in range(0, 11)])}
        events = immobility_events(track, CONFIG)
        assert len(events) == 2 and all(e["team"] is None for e in events)

    def test_a_track_of_one_box_is_not_a_crash(self):
        assert immobile_spans(boxes([(0, 0.5, 0.5)])) == []


class TestStableScores:
    def test_a_confirmed_rise_is_kept(self):
        assert stable_scores([(1.0, 0), (2.0, 5), (3.0, 5)]) == [(2.0, 5)]

    def test_an_unconfirmed_rise_is_not_believed_yet(self):
        # One frame is not evidence: a single hallucinated digit would invent a scoring event.
        assert stable_scores([(1.0, 0), (2.0, 5)]) == []

    def test_a_drop_is_a_misread_not_a_correction(self):
        # An alliance score never falls during a match, so this is the one rule that cleans the
        # timeline for free. The real blue score misread twice in 35 samples.
        readings = [(1.0, 10), (2.0, 10), (3.0, 4), (4.0, 4), (5.0, 10), (6.0, 10)]
        assert [v for _, v in stable_scores(readings)] == [10]

    def test_a_single_spike_never_becomes_a_score(self):
        readings = [(1.0, 5), (2.0, 5), (3.0, 121), (4.0, 5), (5.0, 5)]
        assert [v for _, v in stable_scores(readings)] == [5]

    def test_the_time_recorded_is_when_the_value_was_first_seen(self):
        # Not when it was confirmed -- the score changed at the first sighting, and attributing
        # it a sample later would shift every scoring moment.
        assert stable_scores([(1.0, 0), (7.0, 5), (8.0, 5)]) == [(7.0, 5)]

    def test_unreadable_samples_are_skipped_not_treated_as_zero(self):
        assert [v for _, v in stable_scores([(1.0, 5), (2.0, None), (3.0, 5)])] == [5]

    def test_nothing_from_nothing(self):
        assert stable_scores([]) == []


class TestScoringMoments:
    def test_each_rise_is_a_moment_with_its_size(self):
        moments = scoring_moments([(10.0, 5), (20.0, 12)], "red")
        assert [(m["t_seconds"], m["points"]) for m in moments] == [(10.0, 5), (20.0, 7)]
        assert all(m["alliance"] == "red" for m in moments)

    def test_a_flat_score_produces_no_moments(self):
        assert scoring_moments([], "blue") == []


class TestShotsFromPoints:
    def test_placeholder_point_values_yield_no_shot_count(self):
        # This is the shipped 2026 config: every value is zero. Guessing a unit would turn one
        # scoring moment into a confident, wrong number of shots and poison every accuracy figure.
        assert shots_from_points(5, "teleop", REAL_2026) is None

    def test_a_real_config_divides_cleanly(self):
        config = {"point_values": {"teleop": {"shot_made_high": 5, "shot_made_low": 2}}}
        assert shots_from_points(4, "teleop", config) == 2      # two low goals
        assert shots_from_points(2, "teleop", config) == 1

    def test_a_total_that_matches_no_whole_number_of_shots_is_refused(self):
        config = {"point_values": {"teleop": {"shot_made_high": 5}}}
        assert shots_from_points(7, "teleop", config) is None

    def test_a_missing_phase_is_not_a_crash(self):
        assert shots_from_points(5, "endgame", REAL_2026) is None


class TestToEvents:
    def test_rows_get_identity_and_provenance(self):
        events = to_events([{"t_seconds": 1.0, "event_type": "phase_change"}], "job1", "m1")
        assert len(events) == 1
        event = events[0]
        assert event["job_id"] == "job1" and event["match_id"] == "m1"
        assert event["schema_version"] == 3 and event["source"] == "model"
        assert len(event["event_id"]) == 36

    def test_every_event_gets_its_own_id(self):
        rows = [{"t_seconds": 1.0}, {"t_seconds": 2.0}]
        ids = {e["event_id"] for e in to_events(rows, "job1", "m1")}
        assert len(ids) == 2


class TestMatchAnchor:
    """A clip is not a match. Timing phases from the file start put every boundary 21 seconds
    early on the first real run, and events either side of one landed in the wrong period."""

    def test_agreeing_readings_give_the_zero_time(self):
        from ingest.action_extraction import match_anchor

        # clip t + remaining is constant through a match, and equals when the clock hits zero.
        readings = [(40.0, 131), (50.0, 121), (100.0, 71), (110.0, 61), (130.0, 41)]
        assert match_anchor(readings) == (171.0, 5)

    def test_misreads_do_not_move_the_answer(self):
        from ingest.action_extraction import match_anchor

        # Real data: OCR reads 21 as 27, so a few sums land 6 seconds out. The majority wins.
        readings = [(40.0, 131), (50.0, 121), (90.0, 87), (100.0, 71), (120.0, 57),
                    (130.0, 41), (150.0, 27), (160.0, 11)]
        anchor, agreed = match_anchor(readings)
        assert anchor == 171.0 and agreed == 5

    def test_too_few_agreeing_readings_is_no_answer(self):
        from ingest.action_extraction import match_anchor

        # Two readings agreeing is not an anchor; guessing one shifts the whole match.
        assert match_anchor([(10.0, 20), (20.0, 10)]) is None

    def test_nothing_readable_is_no_answer(self):
        from ingest.action_extraction import match_anchor

        assert match_anchor([(10.0, None), (20.0, None)]) is None

    def test_the_offset_is_the_anchor_less_the_match_length(self):
        from ingest.action_extraction import match_start_offset

        # 15 + 135 = 150 seconds of play ending at clip t=171, so it began at t=21.
        assert match_start_offset(171.0, CONFIG) == 21.0

    def test_phase_boundaries_move_with_the_offset(self):
        events = phase_changes(215.0, CONFIG, start_offset=21.0)
        assert [e["t_seconds"] for e in events] == [36.0, 151.0]

    def test_immobility_phase_is_asked_in_match_time(self):
        # The timestamp stays in clip time -- that is what the player seeks to -- but the phase
        # has to be looked up after removing the offset, or a teleop event reads as auto.
        track = {"track_id": 1, "team": None,
                 "boxes": boxes([(t, 0.5, 0.5) for t in range(25, 36)])}
        events = immobility_events(track, CONFIG, start_offset=21.0)
        # clip t=25 is match t=4, which is auto.
        assert events[0]["t_seconds"] == 25.0
        assert events[0]["phase"] == "auto"
        assert immobility_events(track, CONFIG, start_offset=0.0)[0]["phase"] == "teleop"
