#include "RobotDetector.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <utility>

#include <opencv2/imgproc.hpp>

#include "ContractModels.h"

#ifdef FRC_HAVE_ONNXRUNTIME
#include <onnxruntime_cxx_api.h>
#endif

namespace fs = std::filesystem;

namespace frc::vision {
namespace {

double sigmoid(float value) {
    const double clipped = std::clamp(static_cast<double>(value), -88.0, 88.0);
    return 1.0 / (1.0 + std::exp(-clipped));
}

std::string required_string(const json& value, const char* key, const std::string& fallback) {
    if (!value.contains(key)) return fallback;
    if (!value.at(key).is_string()) throw std::runtime_error(std::string(key) + " must be a string");
    return value.at(key).get<std::string>();
}

template <typename T>
T optional_value(const json& value, const char* key, const T& fallback) {
    if (!value.contains(key)) return fallback;
    return value.at(key).get<T>();
}

DetectorFamily parse_family(const std::string& name) {
    if (name == "auto") return DetectorFamily::kAuto;
    if (name == "yolo") return DetectorFamily::kYolo;
    if (name == "rfdetr") return DetectorFamily::kRfDetr;
    throw std::runtime_error("Detector family must be one of auto, yolo, rfdetr; got: " + name);
}

double intersection_over_union(const Detection& a, const Detection& b) {
    const double x1 = std::max(a.x, b.x);
    const double y1 = std::max(a.y, b.y);
    const double x2 = std::min(a.x + a.w, b.x + b.w);
    const double y2 = std::min(a.y + a.h, b.y + b.h);
    const double overlap = std::max(0.0, x2 - x1) * std::max(0.0, y2 - y1);
    const double combined = a.w * a.h + b.w * b.h - overlap;
    return combined > 0.0 ? overlap / combined : 0.0;
}

/**
 * Clip a normalized box to the frame.
 *
 * A robot leaving the field of view is real, but the off-screen part of its box is not something
 * any later stage can look at, and a box extending past the edge quietly breaks any area or
 * overlap arithmetic downstream. Shrinking from the clipped edge keeps the visible portion
 * rather than sliding the whole box inward.
 */
bool clip_to_frame(Detection& d) {
    const double left = std::max(d.x, 0.0);
    const double top = std::max(d.y, 0.0);
    const double right = std::min(d.x + d.w, 1.0);
    const double bottom = std::min(d.y + d.h, 1.0);
    if (right <= left || bottom <= top) return false;
    d.x = left;
    d.y = top;
    d.w = right - left;
    d.h = bottom - top;
    return true;
}

}  // namespace

DetectorConfig load_detector_config() {
    DetectorConfig config;
    const char* configured_path = std::getenv("FRC_DETECTOR_CONFIG");
    if (configured_path == nullptr || std::string(configured_path).empty()) return config;

    const fs::path config_path(configured_path);
    std::ifstream file(config_path);
    if (!file.is_open()) throw std::runtime_error("Cannot open FRC_DETECTOR_CONFIG: " + config_path.string());
    json value;
    file >> value;
    if (!value.is_object()) throw std::runtime_error("Detector config must be a JSON object");

    config.model_path = required_string(value, "model_path", "");
    if (config.model_path.empty()) throw std::runtime_error("Detector config requires model_path");
    fs::path model_path(config.model_path);
    if (model_path.is_relative()) model_path = config_path.parent_path() / model_path;
    config.model_path = model_path.lexically_normal().string();
    config.model_version = required_string(value, "model_version", config.model_version);
    config.family = parse_family(required_string(value, "family", "auto"));
    config.input_name = required_string(value, "input_name", config.input_name);
    config.boxes_output_name = required_string(value, "boxes_output_name", config.boxes_output_name);
    config.logits_output_name = required_string(value, "logits_output_name", config.logits_output_name);
    config.input_size_from_config = value.contains("input_width") || value.contains("input_height");
    config.input_width = optional_value<int>(value, "input_width", config.input_width);
    config.input_height = optional_value<int>(value, "input_height", config.input_height);
    config.robot_class_id = optional_value<int>(value, "robot_class_id", config.robot_class_id);
    config.background_class_id = optional_value<int>(value, "background_class_id", config.background_class_id);
    config.score_threshold = optional_value<double>(value, "score_threshold", config.score_threshold);
    config.nms_iou = optional_value<double>(value, "nms_iou", config.nms_iou);
    config.sample_rate_hz = optional_value<double>(value, "sample_rate_hz", config.sample_rate_hz);
    config.shot_change_threshold = optional_value<double>(value, "shot_change_threshold", config.shot_change_threshold);
    if (config.input_width <= 0 || config.input_height <= 0 || config.sample_rate_hz <= 0.0 ||
        config.score_threshold <= 0.0 || config.score_threshold > 1.0 ||
        config.nms_iou <= 0.0 || config.nms_iou > 1.0 ||
        config.shot_change_threshold <= 0.0 || config.shot_change_threshold > 1.0) {
        throw std::runtime_error("Detector config has an invalid dimension, threshold, or sample rate");
    }
    return config;
}

// --- pure post-processing ----------------------------------------------------------------------

Letterbox letterbox_for(int source_width, int source_height, int input_size) {
    Letterbox box;
    const int longest = std::max(source_width, source_height);
    if (longest <= 0 || input_size <= 0) return box;
    box.scale = static_cast<double>(input_size) / longest;
    const int scaled_w = static_cast<int>(std::lround(source_width * box.scale));
    const int scaled_h = static_cast<int>(std::lround(source_height * box.scale));
    box.pad_x = (input_size - scaled_w) / 2;
    box.pad_y = (input_size - scaled_h) / 2;
    return box;
}

std::vector<Detection> decode_yolo(const float* data, int64_t dim1, int64_t dim2,
                                   const Letterbox& box, int source_width, int source_height,
                                   double score_threshold, int robot_class_id) {
    std::vector<Detection> detections;
    if (data == nullptr || dim1 <= 0 || dim2 <= 0 || source_width <= 0 || source_height <= 0 ||
        box.scale <= 0.0) {
        return detections;
    }
    // The attribute axis is the short one: an export has thousands of anchors and a handful of
    // attributes. Equal lengths are read as (anchors, attributes), matching the Python runner.
    const bool attributes_first = dim1 < dim2;
    const int64_t anchors = attributes_first ? dim2 : dim1;
    const int64_t attributes = attributes_first ? dim1 : dim2;
    if (attributes < 5) return detections;  // four box values, then at least one class score

    const auto at = [&](int64_t anchor, int64_t attribute) {
        return static_cast<double>(attributes_first ? data[attribute * anchors + anchor]
                                                    : data[anchor * attributes + attribute]);
    };

    for (int64_t anchor = 0; anchor < anchors; ++anchor) {
        int best_class = -1;
        double best_score = 0.0;
        for (int64_t attribute = 4; attribute < attributes; ++attribute) {
            const double score = at(anchor, attribute);
            if (score > best_score) {
                best_score = score;
                best_class = static_cast<int>(attribute - 4);
            }
        }
        if (best_class != robot_class_id || best_score < score_threshold) continue;

        // Model-input pixels back to source pixels: undo the padding, then the scale.
        const double cx = at(anchor, 0);
        const double cy = at(anchor, 1);
        const double bw = at(anchor, 2);
        const double bh = at(anchor, 3);
        Detection detection;
        detection.x = (cx - bw / 2.0 - box.pad_x) / box.scale / source_width;
        detection.y = (cy - bh / 2.0 - box.pad_y) / box.scale / source_height;
        detection.w = bw / box.scale / source_width;
        detection.h = bh / box.scale / source_height;
        detection.confidence = best_score;
        detection.class_id = best_class;
        if (clip_to_frame(detection)) detections.push_back(detection);
    }
    return detections;
}

std::vector<Detection> non_max_suppression(std::vector<Detection> boxes, double iou_threshold) {
    std::stable_sort(boxes.begin(), boxes.end(),
                     [](const Detection& a, const Detection& b) { return a.confidence > b.confidence; });
    std::vector<Detection> kept;
    for (const auto& candidate : boxes) {
        const bool duplicate = std::any_of(
            kept.begin(), kept.end(), [&](const Detection& chosen) {
                return intersection_over_union(chosen, candidate) >= iou_threshold;
            });
        if (!duplicate) kept.push_back(candidate);
    }
    return kept;
}

// --- the session -------------------------------------------------------------------------------

struct RobotDetector::Impl {
#ifdef FRC_HAVE_ONNXRUNTIME
    Ort::Env environment{ORT_LOGGING_LEVEL_WARNING, "frc-analysis"};
    Ort::SessionOptions options;
    std::unique_ptr<Ort::Session> session;
    std::string input_name;
    std::vector<std::string> output_names;
#endif
};

RobotDetector::RobotDetector(DetectorConfig config) : config_(std::move(config)) {
    if (config_.model_path.empty()) return;
    if (!fs::is_regular_file(config_.model_path)) {
        throw std::runtime_error("Detector ONNX model does not exist: " + config_.model_path);
    }
#ifdef FRC_HAVE_ONNXRUNTIME
    impl_ = std::make_unique<Impl>();
    impl_->options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_EXTENDED);
#ifdef _WIN32
    const std::wstring model_path = fs::path(config_.model_path).wstring();
    impl_->session = std::make_unique<Ort::Session>(impl_->environment, model_path.c_str(), impl_->options);
#else
    impl_->session = std::make_unique<Ort::Session>(impl_->environment, config_.model_path.c_str(), impl_->options);
#endif

    Ort::AllocatorWithDefaultOptions allocator;
    const size_t output_count = impl_->session->GetOutputCount();
    if (output_count == 0) throw std::runtime_error("Detector ONNX model has no outputs");

    // One output is a YOLO tensor; two are RF-DETR's dets and labels. The model is a more
    // reliable witness to its own family than a config string somebody typed.
    if (config_.family == DetectorFamily::kAuto) {
        config_.family = output_count == 1 ? DetectorFamily::kYolo : DetectorFamily::kRfDetr;
    }
    const bool is_yolo = config_.family == DetectorFamily::kYolo;
    if (is_yolo && output_count != 1) {
        throw std::runtime_error("Configured as yolo, but the model has " +
                                 std::to_string(output_count) + " outputs, not 1");
    }
    if (!is_yolo && output_count < 2) {
        throw std::runtime_error("Configured as rfdetr, but the model has a single output. "
                                 "A one-output export is YOLO; set family to yolo.");
    }

    if (is_yolo) {
        // With one input and one output there is nothing to choose between, so the model's own
        // names are used and the RF-DETR name settings are simply not consulted.
        impl_->input_name = impl_->session->GetInputNameAllocated(0, allocator).get();
        impl_->output_names.emplace_back(impl_->session->GetOutputNameAllocated(0, allocator).get());
    } else {
        impl_->input_name = config_.input_name;
        impl_->output_names = {config_.boxes_output_name, config_.logits_output_name};
    }

    // An export records the resolution it was trained at. A 960-trained model fed 640-sized input
    // returns boxes that are plausible and wrong, so this is checked rather than assumed: an
    // unset size is taken from the model, and a set one that contradicts it is refused.
    const auto input_shape = impl_->session->GetInputTypeInfo(0).GetTensorTypeAndShapeInfo().GetShape();
    if (input_shape.size() == 4 && input_shape[2] > 0 && input_shape[3] > 0) {
        const int model_h = static_cast<int>(input_shape[2]);
        const int model_w = static_cast<int>(input_shape[3]);
        if (!config_.input_size_from_config) {
            config_.input_height = model_h;
            config_.input_width = model_w;
        } else if (config_.input_height != model_h || config_.input_width != model_w) {
            throw std::runtime_error(
                "Detector config says " + std::to_string(config_.input_width) + "x" +
                std::to_string(config_.input_height) + " but the model declares " +
                std::to_string(model_w) + "x" + std::to_string(model_h) +
                ". Drop input_width/input_height to take the model's own resolution.");
        }
    }
    if (is_yolo && config_.input_width != config_.input_height) {
        throw std::runtime_error("A YOLO export is letterboxed into a square, and this model's "
                                 "input is not square, so the padding would be undefined.");
    }
#else
    throw std::runtime_error(
        "A detector config was supplied but this build has no ONNX Runtime. Build with vcpkg onnxruntime.");
#endif
}

RobotDetector::~RobotDetector() = default;
RobotDetector::RobotDetector(RobotDetector&&) noexcept = default;
RobotDetector& RobotDetector::operator=(RobotDetector&&) noexcept = default;

bool RobotDetector::enabled() const { return impl_ != nullptr; }
const DetectorConfig& RobotDetector::config() const { return config_; }

std::vector<Detection> RobotDetector::infer(const cv::Mat& bgr_frame) const {
    if (!enabled()) return {};
#ifndef FRC_HAVE_ONNXRUNTIME
    (void)bgr_frame;
    return {};
#else
    if (bgr_frame.empty()) return {};
    const bool is_yolo = config_.family == DetectorFamily::kYolo;
    const int source_width = bgr_frame.cols;
    const int source_height = bgr_frame.rows;

    cv::Mat rgb;
    cv::cvtColor(bgr_frame, rgb, cv::COLOR_BGR2RGB);

    cv::Mat prepared;
    Letterbox box;
    if (is_yolo) {
        // Letterbox: fit the long edge, pad the short one with grey. Stretching a 16:9 frame to
        // square moves every box, and the model was trained on letterboxed input.
        box = letterbox_for(source_width, source_height, config_.input_width);
        const int scaled_w = static_cast<int>(std::lround(source_width * box.scale));
        const int scaled_h = static_cast<int>(std::lround(source_height * box.scale));
        cv::Mat resized;
        cv::resize(rgb, resized, cv::Size(scaled_w, scaled_h), 0.0, 0.0, cv::INTER_LINEAR);
        prepared = cv::Mat(config_.input_height, config_.input_width, CV_8UC3,
                           cv::Scalar(114, 114, 114));
        resized.copyTo(prepared(cv::Rect(box.pad_x, box.pad_y, scaled_w, scaled_h)));
    } else {
        cv::resize(rgb, prepared, cv::Size(config_.input_width, config_.input_height), 0.0, 0.0,
                   cv::INTER_LINEAR);
    }

    std::vector<float> input(static_cast<size_t>(3) * config_.input_width * config_.input_height);
    constexpr float kMean[] = {0.485F, 0.456F, 0.406F};
    constexpr float kStd[] = {0.229F, 0.224F, 0.225F};
    const size_t plane = static_cast<size_t>(config_.input_width) * config_.input_height;
    for (int y = 0; y < config_.input_height; ++y) {
        const auto* row = prepared.ptr<cv::Vec3b>(y);
        for (int x = 0; x < config_.input_width; ++x) {
            for (int channel = 0; channel < 3; ++channel) {
                const float normalized = static_cast<float>(row[x][channel]) / 255.0F;
                // YOLO trains on plain 0-1; RF-DETR on ImageNet statistics. Applying the wrong
                // one shifts every pixel, and the model then sees an image unlike anything it
                // was shown in training.
                input[static_cast<size_t>(channel) * plane + static_cast<size_t>(y) * config_.input_width + x] =
                    is_yolo ? normalized : (normalized - kMean[channel]) / kStd[channel];
            }
        }
    }

    const std::array<int64_t, 4> shape = {1, 3, config_.input_height, config_.input_width};
    const auto memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    auto tensor = Ort::Value::CreateTensor<float>(memory, input.data(), input.size(), shape.data(), shape.size());
    const std::array<const char*, 1> input_names = {impl_->input_name.c_str()};
    std::vector<const char*> output_names;
    output_names.reserve(impl_->output_names.size());
    for (const auto& name : impl_->output_names) output_names.push_back(name.c_str());
    auto outputs = impl_->session->Run(Ort::RunOptions{nullptr}, input_names.data(), &tensor, 1,
                                       output_names.data(), output_names.size());

    if (is_yolo) {
        if (outputs.size() != 1 || !outputs[0].IsTensor()) {
            throw std::runtime_error("YOLO ONNX export did not return a single tensor output");
        }
        const auto out_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
        if (out_shape.size() != 3 || out_shape[0] != 1) {
            throw std::runtime_error("YOLO ONNX output is not shaped [1, a, b]");
        }
        auto detections = decode_yolo(outputs[0].GetTensorData<float>(), out_shape[1], out_shape[2],
                                      box, source_width, source_height, config_.score_threshold,
                                      config_.robot_class_id);
        return non_max_suppression(std::move(detections), config_.nms_iou);
    }

    if (outputs.size() != 2 || !outputs[0].IsTensor() || !outputs[1].IsTensor()) {
        throw std::runtime_error("RF-DETR ONNX export did not return tensor outputs dets and labels");
    }
    const auto box_shape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
    const auto logits_shape = outputs[1].GetTensorTypeAndShapeInfo().GetShape();
    if (box_shape.size() != 3 || logits_shape.size() != 3 || box_shape[0] != 1 || logits_shape[0] != 1 ||
        box_shape[1] != logits_shape[1] || box_shape[2] != 4) {
        throw std::runtime_error("RF-DETR ONNX output shapes are not [1, queries, 4] and [1, queries, classes]");
    }
    const int queries = static_cast<int>(box_shape[1]);
    const int class_count = static_cast<int>(logits_shape[2]);
    const float* boxes = outputs[0].GetTensorData<float>();
    const float* logits = outputs[1].GetTensorData<float>();
    std::vector<Detection> detections;
    for (int query = 0; query < queries; ++query) {
        int best_class = -1;
        double best_score = 0.0;
        for (int class_id = 0; class_id < class_count; ++class_id) {
            if (class_id == config_.background_class_id) continue;
            const double score = sigmoid(logits[query * class_count + class_id]);
            if (score > best_score) {
                best_score = score;
                best_class = class_id;
            }
        }
        if (best_class != config_.robot_class_id || best_score < config_.score_threshold) continue;
        const float* raw = boxes + query * 4;
        Detection detection;
        detection.w = std::clamp(static_cast<double>(raw[2]), 0.0, 1.0);
        detection.h = std::clamp(static_cast<double>(raw[3]), 0.0, 1.0);
        detection.x = static_cast<double>(raw[0]) - detection.w / 2.0;
        detection.y = static_cast<double>(raw[1]) - detection.h / 2.0;
        detection.confidence = best_score;
        detection.class_id = best_class;
        if (clip_to_frame(detection)) detections.push_back(detection);
    }
    return detections;
#endif
}

}  // namespace frc::vision
