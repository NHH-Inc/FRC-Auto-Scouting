// Component 1 entry point -- Contract D at SCHEMA_VERSION 2.
//
//     analysis --job <path/to/job.json> --season <path/to/season.json> --out <output/dir>
//
// On success: exit 0, and <out>/events.jsonl, <out>/tracks.jsonl, <out>/result.json exist.
// On failure: nonzero exit, human-readable reason on stderr, and an error_code enum value as
// the LAST LINE of stderr so component 2 can classify without parsing prose.
// Progress goes to stdout as one JSON object per line: {"progress": 0.42, "stage": "tracking"}
//
// The detection/tracking/OCR pipeline is not implemented yet. What is implemented is the
// contract surface, so component 2 and component 3 can integrate against a real binary.

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <vector>

#include "ContractModels.h"

namespace fs = std::filesystem;

namespace {

/** Progress line. `stage` MUST be a value from the stage enum -- component 3 renders it. */
void print_progress(double progress, const char* stage) {
    const json msg = {{"progress", progress}, {"stage", stage}};
    std::cout << msg.dump() << std::endl;
}

/**
 * Fail the way Contract D says to: reason on stderr, then the error_code alone on the last
 * line. Component 2 reads that last line rather than pattern-matching the message.
 */
[[nodiscard]] int fail(const std::string& reason, const char* code) {
    std::cerr << reason << std::endl;
    std::cerr << code << std::endl;
    return 1;
}

/** UUIDv4. Contract B: event_id is generated here, because corrections reference it. */
std::string uuid4() {
    static thread_local std::mt19937_64 rng{std::random_device{}()};
    static constexpr char kHex[] = "0123456789abcdef";
    std::string s(36, '-');
    for (int i = 0; i < 36; ++i) {
        if (i == 8 || i == 13 || i == 18 || i == 23) continue;
        s[i] = kHex[rng() & 0xF];
    }
    s[14] = '4';                                  // version
    s[19] = kHex[(rng() & 0x3) | 0x8];            // variant
    return s;
}

std::string iso_now() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
#ifdef _WIN32
    gmtime_s(&tm, &t);
#else
    gmtime_r(&t, &tm);
#endif
    std::ostringstream out;
    out << std::put_time(&tm, "%Y-%m-%dT%H:%M:%SZ");
    return out.str();
}

}  // namespace

int main(int argc, char* argv[]) {
    std::string job_path;
    std::string season_path;
    std::string out_dir;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--job" && i + 1 < argc) {
            job_path = argv[++i];
        } else if (arg == "--season" && i + 1 < argc) {
            season_path = argv[++i];
        } else if (arg == "--out" && i + 1 < argc) {
            out_dir = argv[++i];
        }
    }

    if (job_path.empty() || out_dir.empty() || season_path.empty()) {
        return fail(
            "Usage: analysis --job <job.json> --season <season.json> --out <dir>",
            frc::error_code::kInternal);
    }

    const std::string started_at = iso_now();

    try {
        std::ifstream job_file(job_path);
        if (!job_file.is_open()) {
            return fail("Failed to open job file: " + job_path, frc::error_code::kInternal);
        }
        json job_json;
        job_file >> job_json;
        const auto job = job_json.get<frc::Job>();

        if (job.schema_version != frc::SCHEMA_VERSION) {
            return fail("Job schema_version " + std::to_string(job.schema_version) +
                            " != " + std::to_string(frc::SCHEMA_VERSION),
                        frc::error_code::kInternal);
        }

        // Contract B requires a string match_id on every event, so a job that never resolved
        // one cannot produce a valid event stream.
        if (!job.match_id.has_value()) {
            return fail("Job has no match_id; cannot attribute events to a match",
                        frc::error_code::kNoMatchData);
        }
        // Contract A guarantees these are non-null once status is downloaded or later, which
        // is the only state component 2 ever hands us a job in.
        if (!job.local_path.has_value() || !job.fps.has_value() || !job.duration.has_value()) {
            return fail("Job is missing media metadata (local_path/fps/duration)",
                        frc::error_code::kInternal);
        }

        std::ifstream season_file(season_path);
        if (!season_file.is_open()) {
            return fail("Failed to open season config: " + season_path,
                        frc::error_code::kInternal);
        }
        json season_json;
        season_file >> season_json;
        const auto season = season_json.get<frc::SeasonConfig>();
        if (season.season != job.season) {
            return fail("Season config is for " + std::to_string(season.season) +
                            " but the job says " + std::to_string(job.season),
                        frc::error_code::kInternal);
        }

        fs::create_directories(out_dir);

        // Stages come from the closed `stage` enum so component 1's stdout and component 3's
        // labels cannot drift apart.
        print_progress(0.05, frc::stage::kDecoding);
        print_progress(0.25, frc::stage::kDetecting);
        print_progress(0.55, frc::stage::kTracking);
        print_progress(0.80, frc::stage::kOcr);
        print_progress(0.95, frc::stage::kEvents);

        // ---- TODO: the actual pipeline.
        //
        // Detection (RF-DETR) -> ByteTrack -> homography -> bumper OCR -> event extraction.
        // Everything below is contract-shaped scaffolding so components 2 and 3 can integrate
        // against a real binary; it does not look at the video yet.
        //
        // When it does: emit every skipped shot-change interval into the owning track's
        // `gaps`, and do NOT split the track at one -- re-identification exists to stitch
        // fragments into a single logical track.

        std::vector<frc::Event> events;
        std::vector<frc::Track> tracks;

        constexpr double kBoxSampleRate = 10.0;
        const double match_start_t = 0.0;

        // One match-level event, to keep the output contract-valid rather than empty.
        // team, track_id and both field coordinates are null on these by definition.
        frc::Event start_event;
        start_event.job_id = job.job_id;
        start_event.match_id = *job.match_id;
        start_event.event_id = uuid4();
        start_event.t_seconds = match_start_t;
        start_event.phase = frc::phase_at(0.0, season);
        start_event.event_type = frc::event_type::kMatchStart;
        start_event.confidence = 1.0;
        start_event.source = "model";
        events.push_back(start_event);

        std::ofstream events_file(fs::path(out_dir) / "events.jsonl");
        for (const auto& e : events) {
            events_file << json(e).dump() << "\n";
        }

        std::ofstream tracks_file(fs::path(out_dir) / "tracks.jsonl");
        for (const auto& t : tracks) {
            tracks_file << json(t).dump() << "\n";
        }

        frc::RunResult result;
        result.job_id = job.job_id;
        result.model_version = "scaffold-0.0.0";
        result.box_sample_rate = kBoxSampleRate;
        result.homography_ok = false;
        result.frames_total = static_cast<int>(*job.duration * *job.fps);
        result.frames_analyzed = 0;
        result.frames_skipped_shot_change = 0;
        result.tracks_emitted = static_cast<int>(tracks.size());
        result.events_emitted = static_cast<int>(events.size());
        // Null while the season's point values are zero placeholders. Doc 0: "Do not invent
        // values to make a test pass."
        result.reconstructed_score = nullptr;
        result.started_at = started_at;
        result.finished_at = iso_now();

        std::ofstream result_file(fs::path(out_dir) / "result.json");
        result_file << json(result).dump(2) << std::endl;

        print_progress(1.0, frc::stage::kEvents);
        return 0;

    } catch (const json::exception& e) {
        return fail(std::string("Malformed JSON: ") + e.what(), frc::error_code::kInternal);
    } catch (const std::exception& e) {
        return fail(std::string("Analysis failed: ") + e.what(),
                    frc::error_code::kAnalysisFailed);
    }
}
