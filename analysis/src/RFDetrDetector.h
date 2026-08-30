#ifndef RFDETR_DETECTOR_H
#define RFDETR_DETECTOR_H

#include <memory>
#include <string>
#include <vector>

#include <opencv2/core.hpp>

namespace frc::vision {

/** A normalized top-left box from the detector. It never crosses Contract D directly. */
struct Detection {
    double x = 0.0;
    double y = 0.0;
    double w = 0.0;
    double h = 0.0;
    double confidence = 0.0;
    int class_id = 0;
};

/**
 * Local, non-contract model settings. Configure with FRC_DETECTOR_CONFIG; never put a model
 * path in a job record because Contract A must remain portable and model-independent.
 */
struct DetectorConfig {
    std::string model_path;
    std::string model_version = "rfdetr-onnx-0.1.0";
    std::string input_name = "input";
    std::string boxes_output_name = "dets";
    std::string logits_output_name = "labels";
    int input_width = 640;
    int input_height = 640;
    int robot_class_id = 0;
    int background_class_id = -1;
    double score_threshold = 0.50;
    double sample_rate_hz = 2.0;
    double shot_change_threshold = 0.55;
};

/** Reads FRC_DETECTOR_CONFIG. No environment setting means detector work is deliberately off. */
DetectorConfig load_detector_config();

/** Runs an RF-DETR ONNX export when a local model is configured. */
class RFDetrDetector {
  public:
    explicit RFDetrDetector(DetectorConfig config);
    ~RFDetrDetector();
    RFDetrDetector(RFDetrDetector&&) noexcept;
    RFDetrDetector& operator=(RFDetrDetector&&) noexcept;
    RFDetrDetector(const RFDetrDetector&) = delete;
    RFDetrDetector& operator=(const RFDetrDetector&) = delete;

    [[nodiscard]] bool enabled() const;
    [[nodiscard]] const DetectorConfig& config() const;
    [[nodiscard]] std::vector<Detection> infer(const cv::Mat& bgr_frame) const;

  private:
    struct Impl;
    DetectorConfig config_;
    std::unique_ptr<Impl> impl_;
};

}  // namespace frc::vision

#endif  // RFDETR_DETECTOR_H
