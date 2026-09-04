cmake_minimum_required(VERSION 3.14)
project(FRCAnalysisBackend)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# OpenCV decodes the video and prepares detector inputs. ONNX Runtime is optional for the Linux
# contract-only CI build; when vcpkg supplies it, the Windows binary includes RF-DETR inference.
find_package(OpenCV REQUIRED COMPONENTS core imgproc videoio calib3d)
find_package(onnxruntime CONFIG QUIET)

# vcpkg supplies this on Robert's Windows machine. Keep the FetchContent fallback so the
# Linux CI job remains self-contained and does not need a second package manager.
find_package(nlohmann_json CONFIG QUIET)
if (NOT TARGET nlohmann_json::nlohmann_json)
    include(FetchContent)
    FetchContent_Declare(
        json
        GIT_REPOSITORY https://github.com/nlohmann/json.git
        GIT_TAG v3.11.2
    )
    FetchContent_MakeAvailable(json)
endif()

# Analysis executable
add_executable(analysis
    src/main.cpp
    src/ContractModels.h
    src/IoUTracker.cpp
    src/IoUTracker.h
    src/RobotDetector.cpp
    src/RobotDetector.h
    src/Homography.cpp
)

target_link_libraries(analysis PRIVATE nlohmann_json::nlohmann_json ${OpenCV_LIBS})

# Tracker tests. The tracker is pure geometry, so it needs neither OpenCV nor a model -- which is
# what makes the awkward cases (crossing robots, occlusions, camera cuts) cheap to test directly.
add_executable(tracker_test
    tests/tracker_test.cpp
    src/IoUTracker.cpp
)
target_link_libraries(tracker_test PRIVATE nlohmann_json::nlohmann_json ${OpenCV_LIBS})

# Detector post-processing tests. The arithmetic between a raw tensor and a box on a robot is
# pure, so it is tested here without a model or ONNX Runtime -- the ONNX session itself is behind
# FRC_HAVE_ONNXRUNTIME, which this target deliberately does not define.
add_executable(detector_test
    tests/detector_test.cpp
    src/RobotDetector.cpp
)
target_link_libraries(detector_test PRIVATE nlohmann_json::nlohmann_json ${OpenCV_LIBS})


if (TARGET onnxruntime::onnxruntime)
    target_link_libraries(analysis PRIVATE onnxruntime::onnxruntime)
    target_compile_definitions(analysis PRIVATE FRC_HAVE_ONNXRUNTIME=1)
endif()

# Installation/Output settings
set_target_properties(analysis PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
