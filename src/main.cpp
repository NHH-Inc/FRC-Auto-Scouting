#include <iostream>
#include <vector>
#include "ScoutingModel.h"
#include "GoogleSheetsClient.h"

int main() {
    std::cout << "FRC Auto-Scouter Model Initialized..." << std::endl;

    // 1. Initialize the Scouting Model
    ScoutingModel scouter;

    // 2. Mock Match Data (This would normally come from TBAClient)
    // Team 254 Match 1
    scouter.addMatchResult(254, {1, 15, 40, 10, true});
    // Team 254 Match 2
    scouter.addMatchResult(254, {2, 18, 45, 10, true});

    // Team 1678 Match 1
    scouter.addMatchResult(1678, {1, 20, 35, 15, true});

    // 3. Process and Get Rankings
    std::vector<TeamScoutingReport> rankings = scouter.getRankingsByTotalPoints();

    std::cout << "\n--- Current Rankings ---" << std::endl;
    for (const auto& report : rankings) {
        std::cout << "Team " << report.teamNumber
                  << " | Avg Points: " << report.totalAvgPoints
                  << " | Win Rate: " << (report.winRate * 100) << "%" << std::endl;
    }

    // 4. Placeholder for Google Sheets Integration
    std::string spreadsheetId = "YOUR_SPREADSHEET_ID";
    GoogleSheetsClient sheetsClient(spreadsheetId);

    // std::cout << "\nUploading to Google Sheets..." << std::endl;
    // sheetsClient.uploadReports(rankings);

    return 0;
}
