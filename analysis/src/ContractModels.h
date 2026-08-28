#ifndef CONTRACT_MODELS_H
#define CONTRACT_MODELS_H

#include <string>
#include <vector>
#include <optional>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace frc {

struct Alliances {
    std::vector<int> red;
    std::vector<int> blue;
};

struct Job {
    int schema_version;
    std::string job_id;
    std::string match_id;
    std::string video_id;
    std::string local_path;
    double start_offset;
    double duration;
    double fps;
    int width;
    int height;
    std::string status;
    std::optional<Alliances> alliances;
    json tba_score;
};

struct Event {
    int schema_version = 1;
    std::string job_id;
    std::string match_id;
    std::string event_id;
    std::optional<int> team;
    int track_id;
    double t_seconds;
    std::string phase;      // auto | teleop | endgame | unknown
    std::string event_type; // shot_attempt, shot_made, etc.
    double confidence;
    std::optional<double> field_x;
    std::optional<double> field_y;
    std::string source = "model";
};

struct Box {
    double t;
    double x;
    double y;
    double w;
    double h;
};

struct Track {
    int schema_version = 1;
    int track_id;
    std::optional<int> team;
    std::string alliance; // red | blue
    std::vector<Box> boxes;
};

// JSON conversion helpers
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Alliances, red, blue)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Job, schema_version, job_id, match_id, video_id, local_path, start_offset, duration, fps, width, height, status, alliances, tba_score)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Event, schema_version, job_id, match_id, event_id, team, track_id, t_seconds, phase, event_type, confidence, field_x, field_y, source)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Box, t, x, y, w, h)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Track, schema_version, track_id, team, alliance, boxes)

} // namespace frc

#endif
