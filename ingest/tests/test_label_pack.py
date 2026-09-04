"""Selection and writing rules for the human labelling pack.

The expensive mistakes here are silent ones: a pack that is mostly one venue generalises badly,
and a frame written without its label file becomes an image the trainer reads as empty. Both look
fine in a directory listing.
"""

import json

import numpy as np
import pytest

from ingest.collection.label_pack import (
    MIN_GAP_SECONDS,
    PackStats,
    build,
    plan_frames,
    sample_times,
    yolo_line,
)


class TestSampleTimes:
    def test_it_skips_the_start_and_end_of_a_clip(self):
        # Intros, replays and "ALLIANCE WINS" cards live at the ends.
        times = sample_times(200.0, 10)
        assert min(times) >= 20.0
        assert max(times) <= 184.0

    def test_frames_are_never_closer_than_the_gap(self):
        times = sorted(sample_times(200.0, 100))
        assert all(b - a >= MIN_GAP_SECONDS - 1e-6 for a, b in zip(times, times[1:]))

    def test_a_clip_too_short_for_two_still_yields_one(self):
        # Six seconds leaves under five usable, which is less than one gap. One frame from the
        # middle beats returning nothing and dropping the venue from the pack entirely.
        assert len(sample_times(6.0, 5)) == 1

    def test_nothing_from_nothing(self):
        assert sample_times(0.0, 5) == []
        assert sample_times(200.0, 0) == []


class TestPlanFrames:
    def test_every_venue_is_covered_before_any_is_revisited(self):
        # Venue count is what buys generalisation -- thresholds tuned on ten venues here did not
        # survive twenty-five. A budget that runs out must not have spent itself on one arena.
        durations = {f"venue{i}": 200.0 for i in range(10)}
        plan = plan_frames(durations, 10)
        assert len({name for name, _ in plan}) == 10

    def test_a_small_budget_still_spreads(self):
        durations = {f"venue{i}": 200.0 for i in range(10)}
        plan = plan_frames(durations, 4)
        assert len(plan) == 4
        assert len({name for name, _ in plan}) == 4

    def test_it_stops_when_segments_run_out_rather_than_looping(self):
        # Two very short clips cannot supply a hundred frames, and repeating them would fill the
        # pack with duplicates of the same moment.
        plan = plan_frames({"a": 30.0, "b": 30.0}, 100)
        assert len(plan) < 100
        assert len(plan) == len(set(plan))

    def test_no_segments_is_not_a_crash(self):
        assert plan_frames({}, 10) == []
        assert plan_frames({"a": 200.0}, 0) == []


class TestYoloLine:
    def test_top_left_and_size_become_centre_and_size(self):
        line = yolo_line({"x": 0.10, "y": 0.20, "w": 0.30, "h": 0.40})
        parts = line.split()
        assert parts[0] == "0"
        assert float(parts[1]) == pytest.approx(0.25)   # 0.10 + 0.30/2
        assert float(parts[2]) == pytest.approx(0.40)   # 0.20 + 0.40/2
        assert float(parts[3]) == pytest.approx(0.30)
        assert float(parts[4]) == pytest.approx(0.40)


class FakeDetector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect(self, image):
        return list(self.boxes)


class Verdict:
    def __init__(self, usable, reason=""):
        self.usable = usable
        self.reason = reason


def frame(value=90):
    return np.full((64, 64, 3), value, dtype=np.uint8)


class TestBuild:
    def test_every_image_gets_a_label_file(self, tmp_path):
        # An image without its .txt is read by the trainer as a frame containing no robots, which
        # is a confident lie rather than a missing file.
        stats = build([("clipA", 1.0, frame()), ("clipB", 2.0, frame())], tmp_path)
        images = sorted(p.stem for p in (tmp_path / "images").glob("*.jpg"))
        labels = sorted(p.stem for p in (tmp_path / "labels").glob("*.txt"))
        assert images == labels
        assert stats.frames_written == 2

    def test_a_frame_with_no_proposals_still_gets_an_empty_label(self, tmp_path):
        build([("clip", 1.0, frame())], tmp_path, detector=FakeDetector([]))
        written = list((tmp_path / "labels").glob("*.txt"))
        assert len(written) == 1
        assert written[0].read_text() == ""

    def test_proposals_are_written_as_yolo_lines(self, tmp_path):
        stats = build([("clip", 1.0, frame())], tmp_path,
                      detector=FakeDetector([{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                                             {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1}]))
        text = next((tmp_path / "labels").glob("*.txt")).read_text()
        assert len(text.strip().splitlines()) == 2
        assert stats.proposals == 2

    def test_unusable_frames_are_rejected_with_a_reason(self, tmp_path):
        # Score cards and sponsor stings teach nothing about robots.
        stats = build([("clip", 1.0, frame()), ("clip", 9.0, frame())], tmp_path,
                      quality_check=lambda img: Verdict(False, "overbright"))
        assert stats.frames_written == 0
        assert stats.rejected_reasons == {"overbright": 2}

    def test_the_manifest_says_a_human_is_required(self, tmp_path):
        # The pack must never look like finished data. Everything in it is a proposal.
        build([("clip", 1.0, frame())], tmp_path, detector=FakeDetector([]))
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["frames"] == 1
        assert all(item["human_review_required"] for item in manifest["items"])
        assert all(item["status"] == "proposed" for item in manifest["items"])

    def test_it_counts_the_frames_that_need_a_human_most(self, tmp_path):
        # Frames the detector found nothing in are exactly the viewpoint gap this pack exists for.
        stats = build([("clip", 1.0, frame()), ("clip", 9.0, frame())], tmp_path,
                      detector=FakeDetector([]))
        assert stats.frames_without_proposals == 2

    def test_the_instructions_ship_with_the_pack(self, tmp_path):
        build([("clip", 1.0, frame())], tmp_path)
        readme = (tmp_path / "README.md").read_text()
        assert "every robot" in readme.lower()
        assert "skip" in readme.lower()
        assert (tmp_path / "data.yaml").exists()

    def test_an_empty_source_still_produces_a_valid_pack(self, tmp_path):
        stats = build([], tmp_path)
        assert stats.frames_written == 0
        assert json.loads((tmp_path / "manifest.json").read_text())["frames"] == 0
