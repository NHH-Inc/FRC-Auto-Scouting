#include "IoUTracker.h"

#include <algorithm>
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

}  // namespace

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

void IoUTracker::update(double t_seconds, const std::vector<Detection>& detections, bool camera_cut) {
    if (camera_cut) {
        for (auto& state : states_) open_gap(state, t_seconds, frc::gap_reason::kShotChange);
        return;
    }

    std::vector<bool> detection_used(detections.size(), false);
    // Greedy matching is deterministic: for each existing track select its highest-IoU unused box.
    for (auto& state : states_) {
        int best = -1;
        double best_iou = minimum_iou_;
        for (size_t index = 0; index < detections.size(); ++index) {
            if (detection_used[index]) continue;
            const double score = iou(state.last_box, detections[index]);
            if (score >= best_iou) {
                best_iou = score;
                best = static_cast<int>(index);
            }
        }
        if (best >= 0) {
            close_gap(state, t_seconds);
            state.last_box = as_box(t_seconds, detections[best]);
            state.track.boxes.push_back(state.last_box);
            state.last_seen = t_seconds;
            state.missed_samples = 0;
            detection_used[best] = true;
        } else {
            ++state.missed_samples;
            if (state.missed_samples >= missed_samples_before_gap_) {
                open_gap(state, state.last_seen, frc::gap_reason::kDetectionLost);
            }
        }
    }
    for (size_t index = 0; index < detections.size(); ++index) {
        if (detection_used[index]) continue;
        State state;
        state.track.track_id = static_cast<int>(states_.size());
        state.last_box = as_box(t_seconds, detections[index]);
        state.track.boxes.push_back(state.last_box);
        state.last_seen = t_seconds;
        states_.push_back(std::move(state));
    }
}

void IoUTracker::finish(double t_seconds) {
    output_.clear();
    output_.reserve(states_.size());
    for (auto& state : states_) {
        close_gap(state, t_seconds);
        if (!state.track.boxes.empty()) output_.push_back(std::move(state.track));
    }
}

const std::vector<frc::Track>& IoUTracker::tracks() const { return output_; }

}  // namespace frc::vision
