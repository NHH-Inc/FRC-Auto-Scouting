#include "RFDetrDetector.h"

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
    config.input_name = required_string(value, "input_name", config.input_name);
    config.boxes_output_name = required_string(value, "boxes_output_name", config.boxes_output_name);
    config.logits_output_name = required_string(value, "logits_output_name", config.logits_output_name);
    config.input_width = optional_value<int>(value, "input_width", config.input_width);
    config.input_height = optional_value<int>(value, "input_height", config.input_height);
    config.robot_class_id = optional_value<int>(value, "robot_class_id", config.robot_class_id);
    config.background_class_id = optional_value<int>(value, "background_class_id", config.background_class_id);
    config.score_threshold = optional_value<double>(value, "score_threshold", config.score_threshold);
    config.sample_rate_hz = optional_value<double>(value, "sample_rate_hz", config.sample_rate_hz);
    config.shot_change_threshold = optional_value<double>(value, "shot_change_threshold", config.shot_change_threshold);
    if (config.input_width <= 0 || config.input_height <= 0 || config.sample_rate_hz <= 0.0 ||
        config.score_threshold <= 0.0 || config.score_threshold > 1.0 ||
        config.shot_change_threshold <= 0.0 || config.shot_change_threshold > 1.0) {
        throw std::runtime_error("Detector config has an invalid dimension, threshold, or sample rate");
    }
    return config;
}

struct RFDetrDetector::Impl {
#ifdef FRC_HAVE_ONNXRUNTIME
    Ort::Env environment{ORT_LOGGING_LEVEL_WARNING, "frc-analysis"};
    Ort::SessionOptions options;
    std::unique_ptr<Ort::Session> session;
    std::string input_name;
    std::string boxes_output_name;
    std::string logits_output_name;
#endif
};

RFDetrDetector::RFDetrDetector(DetectorConfig config) : config_(std::move(config)) {
    if (config_.model_path.empty()) return;
    if (!fs::is_regular_file(config_.model_path)) {
        throw std::runtime_error("RF-DETR ONNX model does not exist: " + config_.model_path);
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
    impl_->input_name = config_.input_name;
    impl_->boxes_output_name = config_.boxes_output_name;
    impl_->logits_output_name = config_.logits_output_name;
#else
    throw std::runtime_error(
        "A detector config was supplied but this build has no ONNX Runtime. Build with vcpkg onnxruntime.");
#endif
}

RFDetrDetector::~RFDetrDetector() = default;
RFDetrDetector::RFDetrDetector(RFDetrDetector&&) noexcept = default;
RFDetrDetector& RFDetrDetector::operator=(RFDetrDetector&&) noexcept = default;

bool RFDetrDetector::enabled() const { return impl_ != nullptr; }
const DetectorConfig& RFDetrDetector::config() const { return config_; }

std::vector<Detection> RFDetrDetector::infer(const cv::Mat& bgr_frame) const {
    if (!enabled()) return {};
#ifndef FRC_HAVE_ONNXRUNTIME
    (void)bgr_frame;
    return {};
#else
    if (bgr_frame.empty()) return {};
    cv::Mat rgb;
    cv::cvtColor(bgr_frame, rgb, cv::COLOR_BGR2RGB);
    cv::Mat resized;
    cv::resize(rgb, resized, cv::Size(config_.input_width, config_.input_height), 0.0, 0.0, cv::INTER_LINEAR);

    std::vector<float> input(static_cast<size_t>(3) * config_.input_width * config_.input_height);
    constexpr float kMean[] = {0.485F, 0.456F, 0.406F};
    constexpr float kStd[] = {0.229F, 0.224F, 0.225F};
    const size_t plane = static_cast<size_t>(config_.input_width) * config_.input_height;
    for (int y = 0; y < config_.input_height; ++y) {
        const auto* row = resized.ptr<cv::Vec3b>(y);
        for (int x = 0; x < config_.input_width; ++x) {
            for (int channel = 0; channel < 3; ++channel) {
                const float normalized = static_cast<float>(row[x][channel]) / 255.0F;
                input[static_cast<size_t>(channel) * plane + static_cast<size_t>(y) * config_.input_width + x] =
                    (normalized - kMean[channel]) / kStd[channel];
            }
        }
    }

    const std::array<int64_t, 4> shape = {1, 3, config_.input_height, config_.input_width};
    const auto memory = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    auto tensor = Ort::Value::CreateTensor<float>(memory, input.data(), input.size(), shape.data(), shape.size());
    const std::array<const char*, 1> input_names = {impl_->input_name.c_str()};
    const std::array<const char*, 2> output_names = {
        impl_->boxes_output_name.c_str(), impl_->logits_output_name.c_str(),
    };
    auto outputs = impl_->session->Run(Ort::RunOptions{nullptr}, input_names.data(), &tensor, 1,
                                       output_names.data(), output_names.size());
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
        const double w = std::clamp(static_cast<double>(raw[2]), 0.0, 1.0);
        const double h = std::clamp(static_cast<double>(raw[3]), 0.0, 1.0);
        const double x = std::clamp(static_cast<double>(raw[0]) - w / 2.0, 0.0, 1.0);
        const double y = std::clamp(static_cast<double>(raw[1]) - h / 2.0, 0.0, 1.0);
        const double clipped_w = std::min(w, 1.0 - x);
        const double clipped_h = std::min(h, 1.0 - y);
        if (clipped_w <= 0.0 || clipped_h <= 0.0) continue;
        detections.push_back({x, y, clipped_w, clipped_h, best_score, best_class});
    }
    return detections;
#endif
}

}  // namespace frc::vision
