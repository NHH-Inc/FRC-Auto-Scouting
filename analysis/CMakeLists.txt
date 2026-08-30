cmake_minimum_required(VERSION 3.14)
project(FRCAnalysisBackend)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# The first real-pipeline milestone is deliberately small: OpenCV opens a real segment,
# measures its actual metadata, and decodes it. ONNX Runtime is added when the detector lands;
# linking it before there is a model to run only makes local setup harder.
find_package(OpenCV REQUIRED COMPONENTS core videoio)

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
)

target_link_libraries(analysis PRIVATE nlohmann_json::nlohmann_json ${OpenCV_LIBS})

# Installation/Output settings
set_target_properties(analysis PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
