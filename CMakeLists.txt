cmake_minimum_required(VERSION 3.10)
project(FRCAutoScouting)

set(CMAKE_CXX_STANDARD 17)

# Look for dependencies
find_package(CURL REQUIRED)

# Include directories
include_directories(${CURL_INCLUDE_DIRS})

# Source files
add_executable(FRCAutoScouting
    src/main.cpp
    src/Models.cpp
    src/Models.h
    src/ScoutingModel.cpp
    src/ScoutingModel.h
    src/GoogleSheetsClient.h
)

# Link libraries
target_link_libraries(FRCAutoScouting ${CURL_LIBRARIES})
