// Tracking behaviour, written against the failures the team reported as "tracking is awful".
//
// Each scenario is a situation that actually happens in a match, with an answer that is known by
// construction. No framework: a tiny assert harness keeps this buildable with the existing CMake
// setup and makes failures readable.

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

#include "../src/IoUTracker.h"

using frc::vision::Detection;
using frc::vision::IoUTracker;

namespace {

int failures = 0;
int checks = 0;

void check(bool ok, const std::string& what) {
    ++checks;
    if (ok) {
        std::printf("  ok   %s\n", what.c_str());
    } else {
        ++failures;
        std::printf("  FAIL %s\n", what.c_str());
    }
}

Detection box(double x, double y, double w = 0.08, double h = 0.12, double conf = 0.9) {
    Detection d;
    d.x = x; d.y = y; d.w = w; d.h = h; d.confidence = conf; d.class_id = 0;
    return d;
}

// The largest jump between consecutive boxes on a track. An identity swap shows up here as a
// sudden leap: a real robot cannot cross the frame between two samples.
double max_jump(const frc::Track& t) {
    double worst = 0.0;
    for (size_t i = 1; i < t.boxes.size(); ++i) {
        const double dx = t.boxes[i].x - t.boxes[i - 1].x;
        const double dy = t.boxes[i].y - t.boxes[i - 1].y;
        worst = std::max(worst, std::hypot(dx, dy));
    }
    return worst;
}

// --- Two robots passing each other -------------------------------------------------------------
// The classic identity swap. One robot travels left-to-right, the other right-to-left, and they
// cross in the middle. Greedy per-track assignment hands the wrong box to whichever track happens
// to be considered first.
void crossing_robots() {
    std::printf("two robots crossing\n");
    IoUTracker tracker;
    for (int step = 0; step <= 10; ++step) {
        const double t = step * 0.2;
        const double a = 0.20 + step * 0.05;   // ->
        const double b = 0.70 - step * 0.05;   // <-
        tracker.update(t, {box(a, 0.50), box(b, 0.50)}, false);
    }
    tracker.finish(2.0);

    const auto& tracks = tracker.tracks();
    check(tracks.size() == 2, "two robots produce two tracks, not more");

    double worst = 0.0;
    for (const auto& t : tracks) worst = std::max(worst, max_jump(t));
    // Each robot moves 0.05 per sample. A swap at the crossing point produces a far larger jump.
    check(worst < 0.12,
          "neither track teleports across the crossing (max jump " + std::to_string(worst) + ")");
}

// --- A fast robot -------------------------------------------------------------------------------
// Boxes are 0.08 wide and the robot moves 0.07 per sample, so consecutive boxes barely overlap.
// Matching against the last known position loses it; predicting where it should be does not.
void fast_robot() {
    std::printf("a fast-moving robot\n");
    IoUTracker tracker;
    for (int step = 0; step <= 8; ++step) {
        tracker.update(step * 0.2, {box(0.10 + step * 0.07, 0.50)}, false);
    }
    tracker.finish(2.0);
    check(tracker.tracks().size() == 1,
          "one robot stays one track (" + std::to_string(tracker.tracks().size()) + " tracks)");
}

// --- A brief occlusion --------------------------------------------------------------------------
// A robot passes behind a game piece for one sample and reappears where physics says it should.
void brief_occlusion() {
    std::printf("a one-sample occlusion\n");
    IoUTracker tracker;
    for (int step = 0; step <= 8; ++step) {
        const double x = 0.20 + step * 0.03;
        if (step == 4) tracker.update(step * 0.2, {}, false);      // hidden
        else           tracker.update(step * 0.2, {box(x, 0.50)}, false);
    }
    tracker.finish(2.0);
    check(tracker.tracks().size() == 1,
          "the track survives the occlusion (" + std::to_string(tracker.tracks().size()) + " tracks)");
}

// --- A camera cut -------------------------------------------------------------------------------
// The one thing tracking must NOT do. Across a cut the robot could be anywhere, so bridging is
// fabrication. Doc 0 forbids it and this guards the rule.
void camera_cut_is_not_bridged() {
    std::printf("a camera cut\n");
    IoUTracker tracker;
    for (int step = 0; step < 4; ++step) tracker.update(step * 0.2, {box(0.20, 0.50)}, false);
    tracker.update(0.8, {}, true);                                  // cut
    for (int step = 5; step < 9; ++step) tracker.update(step * 0.2, {box(0.20, 0.50)}, false);
    tracker.finish(2.0);

    bool has_shot_change = false;
    for (const auto& t : tracker.tracks())
        for (const auto& g : t.gaps)
            if (g.reason == "shot_change") has_shot_change = true;
    check(has_shot_change, "a cut is recorded as a shot_change gap, never silently bridged");
}

// --- Stationary robots --------------------------------------------------------------------------
// Prediction must not invent motion for something that is not moving.
void stationary_robots_stay_put() {
    std::printf("stationary robots\n");
    IoUTracker tracker;
    for (int step = 0; step <= 10; ++step)
        tracker.update(step * 0.2, {box(0.25, 0.40), box(0.65, 0.60)}, false);
    tracker.finish(2.2);
    check(tracker.tracks().size() == 2, "two parked robots stay two tracks");
    double worst = 0.0;
    for (const auto& t : tracker.tracks()) worst = std::max(worst, max_jump(t));
    check(worst < 1e-6, "a parked robot's track does not drift");
}

// --- A robot that disappears for a long time ----------------------------------------------------
// Found by running the pipeline end to end for the first time. Every one of the seven tracks in a
// real match bridged gaps of four to thirteen seconds, jumping up to 0.7 frame widths -- the
// speed gate is a rate, so a long enough gap made it permit the whole frame.
void long_gap_ends_the_track() {
    std::printf("a robot gone for several seconds\n");
    IoUTracker tracker;
    for (int step = 0; step < 6; ++step) tracker.update(step * 0.5, {box(0.20, 0.50)}, false);
    for (int step = 6; step < 14; ++step) tracker.update(step * 0.5, {}, false);   // 4s of nothing
    // Something appears on the far side of the field. It is not the same robot, and nothing
    // observed says it is.
    for (int step = 14; step < 20; ++step) tracker.update(step * 0.5, {box(0.75, 0.50)}, false);
    tracker.finish(10.0);

    check(tracker.tracks().size() == 2,
          "a long absence ends the track rather than handing its identity to whatever appears "
          "next (" + std::to_string(tracker.tracks().size()) + " tracks)");
    double worst = 0.0;
    for (const auto& t : tracker.tracks()) worst = std::max(worst, max_jump(t));
    check(worst < 0.30, "no track contains a jump across the field");
}

// A gap short enough to be an occlusion still belongs to one robot: it is the same argument
// running the other way, and losing this would trade one failure for its mirror image.
void short_gap_keeps_the_track() {
    std::printf("a robot briefly hidden\n");
    IoUTracker tracker;
    for (int step = 0; step < 6; ++step) tracker.update(step * 0.5, {box(0.20, 0.50)}, false);
    tracker.update(3.0, {}, false);
    tracker.update(3.5, {}, false);
    for (int step = 8; step < 12; ++step) tracker.update(step * 0.5, {box(0.22, 0.50)}, false);
    tracker.finish(6.0);
    check(tracker.tracks().size() == 1,
          "a one-second occlusion is still one robot (" +
              std::to_string(tracker.tracks().size()) + " tracks)");
}

// Distance is capped independently of how long the gap was, so a detection far away is never
// claimed even while the track is still alive.
void distant_detection_is_not_claimed() {
    std::printf("a detection too far away to be the same robot\n");
    IoUTracker tracker;
    for (int step = 0; step < 6; ++step) tracker.update(step * 0.5, {box(0.20, 0.50)}, false);
    tracker.update(3.0, {}, false);
    tracker.update(3.5, {box(0.70, 0.50)}, false);   // half the frame away, 1s later
    tracker.finish(5.0);
    check(tracker.tracks().size() == 2,
          "half a frame in one second starts a new track (" +
              std::to_string(tracker.tracks().size()) + " tracks)");
}

// Ids are handed out from a counter, so retiring one track cannot renumber another. Two tracks
// sharing an id would silently merge two robots in every downstream per-team total.
void ids_are_unique() {
    std::printf("track ids after a retirement\n");
    IoUTracker tracker;
    for (int step = 0; step < 6; ++step) tracker.update(step * 0.5, {box(0.20, 0.50)}, false);
    for (int step = 6; step < 14; ++step) tracker.update(step * 0.5, {}, false);
    for (int step = 14; step < 20; ++step)
        tracker.update(step * 0.5, {box(0.75, 0.50), box(0.30, 0.30)}, false);
    tracker.finish(10.0);
    std::vector<int> ids;
    for (const auto& t : tracker.tracks()) ids.push_back(t.track_id);
    std::sort(ids.begin(), ids.end());
    check(std::adjacent_find(ids.begin(), ids.end()) == ids.end(), "every track id is distinct");
}

}  // namespace

int main() {
    crossing_robots();
    fast_robot();
    brief_occlusion();
    camera_cut_is_not_bridged();
    stationary_robots_stay_put();
    long_gap_ends_the_track();
    short_gap_keeps_the_track();
    distant_detection_is_not_claimed();
    ids_are_unique();
    std::printf("\n%d checks, %d failed\n", checks, failures);
    return failures == 0 ? 0 : 1;
}
