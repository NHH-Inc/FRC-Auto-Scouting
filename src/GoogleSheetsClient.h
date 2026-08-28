#ifndef GOOGLE_SHEETS_CLIENT_H
#define GOOGLE_SHEETS_CLIENT_H

#include "Models.h"
#include <string>
#include <vector>

class GoogleSheetsClient {
public:
    GoogleSheetsClient(const std::string& spreadsheetId);

    // Uploads a list of team reports to the spreadsheet
    bool uploadReports(const std::vector<TeamScoutingReport>& reports);

private:
    std::string spreadsheetId;
    // Logic for OAuth2 and REST API calls would go here
};

#endif
