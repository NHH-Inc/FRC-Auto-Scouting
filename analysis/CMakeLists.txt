cmake_minimum_required(VERSION 3.14)
project(FRCAnalysisBackend)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Fetch nlohmann/json
include(FetchContent)
FetchContent_Declare(
    json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.2
)
FetchContent_MakeAvailable(json)

# Analysis executable
add_executable(analysis
    src/main.cpp
    src/ContractModels.h
)

target_link_libraries(analysis PRIVATE nlohmann_json::nlohmann_json)

# Installation/Output settings
set_target_properties(analysis PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
