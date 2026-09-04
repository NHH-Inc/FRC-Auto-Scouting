#ifndef ROBOT_DETECTOR_H
#define ROBOT_DETECTOR_H

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

/** Which export the ONNX file is. The two families disagree on every step of pre- and
 *  post-processing, so running one as the other produces plausible, meaningless boxes. */
enum class DetectorFamily {
    kAuto,    //!< Decide from the loaded model's outputs: one means YOLO, two mean RF-DETR.
    kYolo,    //!< One tensor, (1, 4+classes, anchors) or its transpose. /255, letterboxed, needs NMS.
    kRfDetr,  //!< Two tensors, dets + labels. ImageNet-normalised, stretched to square, no NMS.
};

/**
 * Local, non-contract model settings. Configure with FRC_DETECTOR_CONFIG; never put a model
 * path in a job record because Contract A must remain portable and model-independent.
 */
struct DetectorConfig {
    std::string model_path;
    std::string model_version = "robot-onnx-0.1.0";
    DetectorFamily family = DetectorFamily::kAuto;
    std::string input_name = "images";
    std::string boxes_output_name = "dets";
    std::string logits_output_name = "labels";
    int input_width = 640;
    int input_height = 640;
    //: Whether input_width/input_height came from the file rather than from these defaults. An
    //: export records its own training resolution; trusting a default over that silently
    //: mis-scales every box, so an absent setting is filled from the model and a present one
    //: that contradicts the model is refused.
    bool input_size_from_config = false;
    int robot_class_id = 0;
    int background_class_id = -1;
    double score_threshold = 0.50;
    //: IoU above which two candidates are the same object. A raw YOLO tensor holds a prediction
    //: per anchor, so one robot arrives as a cluster; without suppression every count downstream
    //: is inflated. RF-DETR needs none -- its queries are already one-per-object.
    double nms_iou = 0.50;
    double sample_rate_hz = 2.0;
    double shot_change_threshold = 0.55;
};

/** Reads FRC_DETECTOR_CONFIG. No environment setting means detector work is deliberately off. */
DetectorConfig load_detector_config();

// --- pure post-processing, exposed so it can be tested without a model or ONNX Runtime --------

/** How a source frame was fitted into the model's square input, preserving aspect ratio. */
struct Letterbox {
    double scale = 1.0;  //!< model-input pixels per source pixel
    int pad_x = 0;       //!< left padding, in model-input pixels
    int pad_y = 0;       //!< top padding, in model-input pixels
};

Letterbox letterbox_for(int source_width, int source_height, int input_size);

/**
 * Decode a raw YOLO tensor into normalized boxes, before suppression.
 *
 * The layout is checked rather than assumed: YOLOv8/11 export (1, 4+classes, anchors) and older
 * exports (1, anchors, 4+classes). Transposing the wrong one produces boxes that look plausible
 * and are meaningless, so the axis matching the attribute count decides.
 */
std::vector<Detection> decode_yolo(const float* data, int64_t dim1, int64_t dim2,
                                   const Letterbox& box, int source_width, int source_height,
                                   double score_threshold, int robot_class_id);

/** Greedy suppression: keep the most confident box, drop what overlaps it, repeat. */
std::vector<Detection> non_max_suppression(std::vector<Detection> boxes, double iou_threshold);

/** Runs a trained ONNX detector when a local model is configured. */
class RobotDetector {
  public:
    explicit RobotDetector(DetectorConfig config);
    ~RobotDetector();
    RobotDetector(RobotDetector&&) noexcept;
    RobotDetector& operator=(RobotDetector&&) noexcept;
    RobotDetector(const RobotDetector&) = delete;
    RobotDetector& operator=(const RobotDetector&) = delete;

    [[nodiscard]] bool enabled() const;
    [[nodiscard]] const DetectorConfig& config() const;
    [[nodiscard]] std::vector<Detection> infer(const cv::Mat& bgr_frame) const;

  private:
    struct Impl;
    DetectorConfig config_;
    std::unique_ptr<Impl> impl_;
};

}  // namespace frc::vision

#endif  // ROBOT_DETECTOR_H
