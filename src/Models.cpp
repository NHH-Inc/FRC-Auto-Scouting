#include "Models.h"
#include <numeric>

void TeamScoutingReport::calculateAverages() {
    if (matchHistory.empty()) return;

    matchesPlayed = matchHistory.size();

    double totalAuto = 0;
    double totalTeleop = 0;
    double totalEndgame = 0;
    int totalWins = 0;

    for (const auto& match : matchHistory) {
        totalAuto += match.autoPoints;
        totalTeleop += match.teleopPoints;
        totalEndgame += match.endgamePoints;
        if (match.win) totalWins++;
    }

    avgAutoPoints = totalAuto / matchesPlayed;
    avgTeleopPoints = totalTeleop / matchesPlayed;
    avgEndgamePoints = totalEndgame / matchesPlayed;
    totalAvgPoints = avgAutoPoints + avgTeleopPoints + avgEndgamePoints;
    winRate = (double)totalWins / matchesPlayed;
}
