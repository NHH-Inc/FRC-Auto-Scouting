#ifndef IOU_TRACKER_H
#define IOU_TRACKER_H

#include <optional>
#include <vector>

#include "ContractModels.h"
#include "RFDetrDetector.h"

namespace frc::vision {

/** A deliberately simple, deterministic tracker used until ByteTrack appearance re-ID lands. */
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
    };

    void open_gap(State& state, double start, const char* reason);
    void close_gap(State& state, double end);
    double minimum_iou_;
    int missed_samples_before_gap_;
    std::vector<State> states_;
    std::vector<frc::Track> output_;
};

}  // namespace frc::vision

#endif  // IOU_TRACKER_H
