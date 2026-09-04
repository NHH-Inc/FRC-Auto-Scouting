"""Per-team statistics — the numbers a scout actually reads off the spreadsheet.

These are the last stop before a human makes a pick-list decision, so a wrong number here is worse
than a missing one: nothing downstream flags it and nobody re-derives it by hand.
"""

from ingest.stats import team_stats


def event(team, kind, t, **extra):
    row = {"team": team, "event_type": kind, "t_seconds": t, "confidence": 1.0,
           "track_id": 1, "phase": "teleop"}
    row.update(extra)
    return row


def stats_for(events, team=254):
    return team_stats(team, events, None, None, 1)


class TestShootingAccuracy:
    def test_attempts_and_makes_are_separate_events(self):
        # The golden fixture has 80 attempts and 55 makes, none sharing a timestamp: a shot is
        # logged when taken and again if it scores.
        events = ([event(254, "shot_attempt", float(i)) for i in range(8)]
                  + [event(254, "shot_made", i + 0.4) for i in range(5)])
        s = stats_for(events)
        assert s["shot_attempts"] == 8
        assert s["shots_made"] == 5
        assert s["shot_accuracy"] == 5 / 8

    def test_makes_without_attempts_do_not_report_nonsense(self):
        # A scout under time pressure logs the makes and misses the attempts. Reporting
        # "1 made of 0 attempted, accuracy unknown" reads as a broken tool rather than as
        # missing input, and a robot cannot score more shots than it took.
        s = stats_for([event(254, "shot_made", 10.0)])
        assert s["shots_made"] == 1
        assert s["shot_attempts"] == 1
        assert s["shot_accuracy"] == 1.0

    def test_accuracy_can_never_exceed_one(self):
        events = ([event(254, "shot_attempt", 1.0)]
                  + [event(254, "shot_made", float(i)) for i in range(2, 7)])
        s = stats_for(events)
        assert s["shot_accuracy"] <= 1.0

    def test_a_robot_that_never_shot_has_no_accuracy(self):
        # Zero of zero is not zero percent, it is unknown. A pick list must be able to tell the
        # difference between "missed everything" and "never tried".
        s = stats_for([event(254, "reload", 5.0)])
        assert s["shot_attempts"] == 0
        assert s["shots_made"] == 0
        assert s["shot_accuracy"] is None

    def test_misses_alone_are_zero_percent_not_unknown(self):
        s = stats_for([event(254, "shot_attempt", float(i)) for i in range(4)])
        assert s["shot_accuracy"] == 0.0


class TestScoping:
    def test_another_team_s_events_are_not_counted(self):
        events = [event(254, "shot_made", 1.0), event(1678, "shot_made", 2.0)]
        assert stats_for(events, team=254)["shots_made"] == 1

    def test_unattributed_events_are_not_counted(self):
        # This is the whole reason a real match exported zero rows: the analyzer's events carry
        # no team, and they must not be silently credited to anyone.
        events = [event(None, "shot_made", 1.0), event(254, "shot_made", 2.0)]
        assert stats_for(events, team=254)["shots_made"] == 1

    def test_the_contract_shape_is_intact(self):
        # Contract E: fields may be added additively; none renamed.
        s = stats_for([event(254, "shot_made", 1.0)])
        for field in ("team", "event_key", "min_confidence", "matches_played", "cycles",
                      "avg_cycle_seconds", "shot_attempts", "shots_made", "shot_accuracy",
                      "avg_shot_interval_seconds", "reloads", "defense_seconds",
                      "immobile_seconds", "fouls", "low_confidence_events"):
            assert field in s, field

    def test_no_events_at_all_is_not_a_crash(self):
        s = stats_for([])
        assert s["shots_made"] == 0
        assert s["shot_accuracy"] is None
        assert s["avg_cycle_seconds"] is None
