#include "IoUTracker.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

namespace frc::vision {
namespace {

double iou(const frc::Box& a, const Detection& b) {
    const double left = std::max(a.x, b.x);
    const double top = std::max(a.y, b.y);
    const double right = std::min(a.x + a.w, b.x + b.w);
    const double bottom = std::min(a.y + a.h, b.y + b.h);
    const double intersection = std::max(0.0, right - left) * std::max(0.0, bottom - top);
    const double union_area = a.w * a.h + b.w * b.h - intersection;
    return union_area > 0.0 ? intersection / union_area : 0.0;
}

frc::Box as_box(double t, const Detection& detection) {
    return {t, detection.x, detection.y, detection.w, detection.h};
}

/**
 * How far a box centre may travel per second, in frame widths, and still be the same robot.
 *
 * Prediction alone cannot rescue the first step of a track: velocity needs two observations, and
 * a track that dies before its second one never gets them. That is the chicken-and-egg that left
 * a fast robot as nine separate tracks even after prediction was added -- every sample it moved
 * far enough to miss on IoU, so every sample it started over.
 *
 * A displacement gate breaks the cycle using physics instead of history. An FRC robot is
 * drivetrain-limited, so across a fifth of a second it simply cannot cross the frame. Matching a
 * box that near is safe; matching one further away would be claiming a robot teleported.
 *
 * Deliberately generous, because normalised speed depends on zoom -- the same robot moves through
 * far more of the frame in a tight shot than a wide one. It only has to exclude the absurd.
 */
constexpr double kMaxCentreSpeed = 1.0;

/**
 * The furthest a centre may move across a gap and still be believed to be the same robot.
 *
 * The speed gate above is a rate, so it grows without limit as a gap lengthens: over a thirteen
 * second occlusion it permits thirteen frame widths, which is the whole frame several times over
 * and therefore no constraint at all. The first real end-to-end run showed exactly that -- every
 * one of seven tracks jumped between 0.4 and 0.7 frame widths across gaps of four to thirteen
 * seconds, silently trading one robot's identity for another's.
 *
 * A rate needs a ceiling. Six robots on a field look alike, so past a few robot-widths of
 * displacement "it is the nearest one" stops being evidence and starts being a guess.
 */
constexpr double kMaxBridgeDistance = 0.30;

/**
 * How long a track may go unseen before it ends.
 *
 * This is the same argument the shot_change rule already makes. A cut is not bridged because
 * across it a robot could be anywhere; after several seconds of occlusion the same is true, and
 * the tracker has no more reason to claim continuity than it does across a cut. Ending the track
 * and starting a new one says what is actually known: two stretches of observation that may or
 * may not be the same robot. Claiming one identity across the gap would be inventing the part
 * nobody saw.
 *
 * Deliberately generous, because the distance ceiling above is what actually discriminates. Of
 * the twelve long gaps the first real run bridged, nine moved 0.25 to 0.70 frame widths and three
 * moved under 0.07; distance alone separates them exactly. This only has to stop a track waiting
 * indefinitely for something to wander into range. At the 2 Hz the analyzer samples at, it is
 * twelve missed samples.
 */
constexpr double kMaxGapSeconds = 6.0;

/** Centre-to-centre distance between a predicted box and a detection. */
double centre_distance(const frc::Box& a, const Detection& b) {
    const double dx = (a.x + a.w / 2.0) - (b.x + b.w / 2.0);
    const double dy = (a.y + a.h / 2.0) - (b.y + b.h / 2.0);
    return std::sqrt(dx * dx + dy * dy);
}

/** Median of a small sample. Used for velocity so one stray box cannot set the direction. */
double median_of(std::vector<double> values) {
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    const size_t mid = values.size() / 2;
    return values.size() % 2 ? values[mid] : (values[mid - 1] + values[mid]) / 2.0;
}

}  // namespace

frc::Box IoUTracker::predict(const State& state, double t) {
    const auto& recent = state.recent;
    frc::Box out = state.last_box;
    if (recent.size() < 2) return out;   // nothing to infer motion from yet

    // Per-interval slopes over the last few observations; the median resists a single bad box.
    std::vector<double> vx, vy;
    const size_t first = recent.size() > 4 ? recent.size() - 4 : 0;
    for (size_t i = first + 1; i < recent.size(); ++i) {
        const double dt = recent[i].t - recent[i - 1].t;
        if (dt > 1e-9) {
            vx.push_back((recent[i].x - recent[i - 1].x) / dt);
            vy.push_back((recent[i].y - recent[i - 1].y) / dt);
        }
    }
    if (vx.empty()) return out;

    const double dt = t - state.last_box.t;
    if (dt <= 0.0) return out;
    out.x += median_of(vx) * dt;
    out.y += median_of(vy) * dt;
    return out;
}

IoUTracker::IoUTracker(double minimum_iou, int missed_samples_before_gap)
    : minimum_iou_(minimum_iou), missed_samples_before_gap_(missed_samples_before_gap) {}

void IoUTracker::open_gap(State& state, double start, const char* reason) {
    if (!state.open_gap.has_value()) state.open_gap = frc::Gap{start, start, reason};
}

void IoUTracker::close_gap(State& state, double end) {
    if (!state.open_gap.has_value()) return;
    if (end > state.open_gap->start) {
        state.open_gap->end = end;
        state.track.gaps.push_back(*state.open_gap);
    }
    state.open_gap.reset();
}

void IoUTracker::retire_stale(double t_seconds) {
    std::vector<State> surviving;
    surviving.reserve(states_.size());
    for (auto& state : states_) {
        if (t_seconds - state.last_seen <= kMaxGapSeconds) {
            surviving.push_back(std::move(state));
            continue;
        }
        // The track ends at its last real observation. The interval after that belongs to no
        // track, rather than being written as a gap inside one.
        state.open_gap.reset();
        if (!state.track.boxes.empty()) retired_.push_back(std::move(state.track));
    }
    states_ = std::move(surviving);
}

void IoUTracker::update(double t_seconds, const std::vector<Detection>& detections, bool camera_cut) {
    retire_stale(t_seconds);
    if (camera_cut) {
        for (auto& state : states_) open_gap(state, t_seconds, frc::gap_reason::kShotChange);
        return;
    }

    std::vector<bool> detection_used(detections.size(), false);
    std::vector<bool> track_matched(states_.size(), false);

    // Score every plausible pairing against where each track is PREDICTED to be, then take the
    // strongest pairing first. Scoring against the last known box loses any robot that moved;
    // resolving in track order lets two crossing robots trade identities.
    struct Candidate { double score; size_t track; size_t detection; };
    std::vector<Candidate> candidates;
    for (size_t s = 0; s < states_.size(); ++s) {
        const frc::Box expected = predict(states_[s], t_seconds);
        const double dt = std::max(1e-6, t_seconds - states_[s].last_box.t);
        const double reach = std::min(kMaxCentreSpeed * dt, kMaxBridgeDistance);
        for (size_t d = 0; d < detections.size(); ++d) {
            const double overlap = iou(expected, detections[d]);
            if (overlap >= minimum_iou_) {
                candidates.push_back({overlap, s, d});
                continue;
            }
            // No overlap, but close enough that a robot could plausibly have moved there. Scored
            // strictly below any genuine overlap, so a real IoU match always wins the assignment
            // and this only decides cases nothing else claims.
            const double distance = centre_distance(expected, detections[d]);
            if (distance <= reach) {
                const double proximity = 1.0 - distance / reach;
                candidates.push_back({minimum_iou_ * 0.5 * proximity, s, d});
            }
        }
    }
    // Ties broken by index so the result does not depend on sort implementation.
    std::sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
        if (a.score != b.score) return a.score > b.score;
        if (a.track != b.track) return a.track < b.track;
        return a.detection < b.detection;
    });

    for (const auto& c : candidates) {
        if (track_matched[c.track] || detection_used[c.detection]) continue;
        State& state = states_[c.track];
        close_gap(state, t_seconds);
        state.last_box = as_box(t_seconds, detections[c.detection]);
        state.track.boxes.push_back(state.last_box);
        state.recent.push_back(state.last_box);
        if (state.recent.size() > 5) state.recent.erase(state.recent.begin());
        state.last_seen = t_seconds;
        state.missed_samples = 0;
        track_matched[c.track] = true;
        detection_used[c.detection] = true;
    }

    for (size_t s = 0; s < states_.size(); ++s) {
        if (track_matched[s]) continue;
        State& state = states_[s];
        ++state.missed_samples;
        if (state.missed_samples >= missed_samples_before_gap_) {
            open_gap(state, state.last_seen, frc::gap_reason::kDetectionLost);
        }
    }
    for (size_t index = 0; index < detections.size(); ++index) {
        if (detection_used[index]) continue;
        State state;
        state.track.track_id = next_track_id_++;
        state.last_box = as_box(t_seconds, detections[index]);
        state.track.boxes.push_back(state.last_box);
        state.recent.push_back(state.last_box);
        state.last_seen = t_seconds;
        states_.push_back(std::move(state));
    }
}

void IoUTracker::finish(double t_seconds) {
    output_.clear();
    output_.reserve(states_.size() + retired_.size());
    for (auto& track : retired_) output_.push_back(std::move(track));
    retired_.clear();
    for (auto& state : states_) {
        close_gap(state, t_seconds);
        if (!state.track.boxes.empty()) output_.push_back(std::move(state.track));
    }
    // Retired tracks are appended as they end, so order by id to keep output deterministic.
    std::sort(output_.begin(), output_.end(),
              [](const frc::Track& a, const frc::Track& b) { return a.track_id < b.track_id; });
}

const std::vector<frc::Track>& IoUTracker::tracks() const { return output_; }

}  // namespace frc::vision
