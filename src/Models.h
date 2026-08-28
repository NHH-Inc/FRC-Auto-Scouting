#ifndef MODELS_H
#define MODELS_H

#include <string>
#include <vector>

struct MatchData {
    int matchNumber;
    int autoPoints;
    int teleopPoints;
    int endgamePoints;
    bool win;
    // Add more specific FRC metrics here (e.g., pieces scored, climb level)
};

struct TeamScoutingReport {
    int teamNumber;
    std::string teamName;

    // Aggregated Stats
    double avgAutoPoints = 0;
    double avgTeleopPoints = 0;
    double avgEndgamePoints = 0;
    double totalAvgPoints = 0;
    double winRate = 0;

    int matchesPlayed = 0;

    std::vector<MatchData> matchHistory;

    void calculateAverages();
};

#endif
