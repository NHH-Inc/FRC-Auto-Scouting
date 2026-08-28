#include "ScoutingModel.h"
#include <algorithm>

void ScoutingModel::addMatchResult(int teamNumber, const MatchData& match) {
    if (teamReports.find(teamNumber) == teamReports.end()) {
        auto report = std::make_shared<TeamScoutingReport>();
        report->teamNumber = teamNumber;
        teamReports[teamNumber] = report;
    }

    teamReports[teamNumber]->matchHistory.push_back(match);
    teamReports[teamNumber]->calculateAverages();
}

std::vector<TeamScoutingReport> ScoutingModel::getRankingsByTotalPoints() const {
    std::vector<TeamScoutingReport> rankings;
    for (const auto& [teamNum, report] : teamReports) {
        rankings.push_back(*report);
    }

    std::sort(rankings.begin(), rankings.end(), [](const TeamScoutingReport& a, const TeamScoutingReport& b) {
        return a.totalAvgPoints > b.totalAvgPoints;
    });

    return rankings;
}

std::shared_ptr<TeamScoutingReport> ScoutingModel::getTeamReport(int teamNumber) {
    if (teamReports.count(teamNumber)) {
        return teamReports[teamNumber];
    }
    return nullptr;
}
