#ifndef SCOUTING_MODEL_H
#define SCOUTING_MODEL_H

#include "Models.h"
#include <map>
#include <memory>

class ScoutingModel {
public:
    void addMatchResult(int teamNumber, const MatchData& match);
    std::vector<TeamScoutingReport> getRankingsByTotalPoints() const;
    std::shared_ptr<TeamScoutingReport> getTeamReport(int teamNumber);

private:
    std::map<int, std::shared_ptr<TeamScoutingReport>> teamReports;
};

#endif
