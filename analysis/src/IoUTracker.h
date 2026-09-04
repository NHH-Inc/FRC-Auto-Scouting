#ifndef IOU_TRACKER_H
#define IOU_TRACKER_H

#include <optional>
#include <vector>

#include "ContractModels.h"
#include "RobotDetector.h"

namespace frc::vision {

/**
 * A deterministic tracker that matches detections to where a robot SHOULD be, not where it last
 * was.
 *
 * The naive version matched each detection against the track's last known box. That fails on the
 * most ordinary thing a robot does -- move. With boxes around 0.08 wide and a robot crossing 0.07
 * per sample, consecutive boxes barely overlap, IoU falls under the threshold, and the track dies
 * and respawns every frame. Measured on a synthetic straight-line run, one robot became NINE
 * tracks, which is what "the tracking is awful" looks like from the inside.
 *
 * So each track carries a velocity, estimated from its recent boxes, and matching happens against
 * the predicted position. A robot moving steadily is then trivially matched, and a robot that
 * vanishes behind a game piece for a sample or two is picked up again where physics says it went.
 *
 * Assignment is global rather than per-track: every plausible (track, detection) pair is scored,
 * and the strongest pairing is taken first. Iterating tracks in order and letting each grab its
 * favourite box is what lets two robots swap identities as they cross -- whichever track is
 * considered first takes the box it likes, even when that box belongs unambiguously to the other.
 *
 * Velocity is a median of recent per-interval slopes, not an average. One badly-placed box
 * otherwise drags the prediction with it, and a wrong prediction is worse than no prediction: it
 * actively pulls the track onto whatever is near the invented position.
 */
class IoUTracker {
  public:
    explicit IoUTracker(double minimum_iou = 0.20, int missed_samples_before_gap = 2);

    /** Adds boxes for one sampled frame; camera cuts are skipped and recorded as shot_change gaps. */
    void update(double t_seconds, const std::vector<Detection>& detections, bool camera_cut);
    /** Closes outstanding intervals at the end of the segment; tracks are never split. */
    void finish(double t_seconds);
    [[nodiscard]] const std::vector<frc::Track>& tracks() const;

  private:
    struct State {
        frc::Track track;
        frc::Box last_box;
        double last_seen = 0.0;
        int missed_samples = 0;
        std::optional<frc::Gap> open_gap;
        /** Recent observations, newest last, used only to estimate velocity. */
        std::vector<frc::Box> recent;
    };

    /** Where this track's box is expected to be at `t`, given its recent motion. */
    [[nodiscard]] static frc::Box predict(const State& state, double t);

    void open_gap(State& state, double start, const char* reason);
    void close_gap(State& state, double end);
    /** Ends tracks that have gone unseen too long to still be identifiable. */
    void retire_stale(double t_seconds);
    double minimum_iou_;
    int missed_samples_before_gap_;
    std::vector<State> states_;
    /** Tracks that ended before the segment did. */
    std::vector<frc::Track> retired_;
    /** Ids are handed out in order and never reused, so retiring a track cannot renumber another. */
    int next_track_id_ = 0;
    std::vector<frc::Track> output_;
};

}  // namespace frc::vision

#endif  // IOU_TRACKER_H
