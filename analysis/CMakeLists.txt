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
    src/RFDetrDetector.cpp
    src/RFDetrDetector.h
    src/Homography.cpp
)

target_link_libraries(analysis PRIVATE nlohmann_json::nlohmann_json ${OpenCV_LIBS})
if (TARGET onnxruntime::onnxruntime)
    target_link_libraries(analysis PRIVATE onnxruntime::onnxruntime)
    target_compile_definitions(analysis PRIVATE FRC_HAVE_ONNXRUNTIME=1)
endif()

# Installation/Output settings
set_target_properties(analysis PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
