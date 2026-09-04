/**
 * Project Tengen — Sheets export endpoint.
 *
 * Paste this into a spreadsheet's Apps Script editor (Extensions > Apps Script) and deploy it as
 * a Web App. It runs as the sheet's owner inside Workspace, so it needs no Google Cloud project
 * and no service account — which is the whole point, since school accounts usually have Cloud
 * switched off.
 *
 * Setup, once:
 *   1. Open the spreadsheet > Extensions > Apps Script. Replace everything with this file.
 *   2. Edit SECRET below to a long random string. Keep it; the ingest service needs the same one.
 *   3. Deploy > New deployment > type "Web app".
 *        Execute as:      Me
 *        Who has access:  Anyone
 *      "Anyone" is required — the ingest service is not signed in as a Google user. That is why
 *      the secret exists: the URL alone must not be enough to write to your sheet.
 *   4. Copy the /exec URL. Put both values in ingest/.env, which is git-ignored:
 *        APPS_SCRIPT_URL=https://script.google.com/macros/s/..../exec
 *        APPS_SCRIPT_SECRET=the same string as SECRET below
 *
 * Re-deploy after any edit: Apps Script serves the last *deployed* version, not the last saved
 * one, so an edited-but-undeployed script keeps running the old code and looks like nothing
 * changed.
 */

var SECRET = 'CHANGE-ME-to-a-long-random-string';

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);

    if (!SECRET || SECRET === 'CHANGE-ME-to-a-long-random-string') {
      return json({ ok: false, error: 'the script SECRET has not been set' });
    }
    if (body.secret !== SECRET) {
      // Deliberately vague: a precise message would help someone guess.
      return json({ ok: false, error: 'rejected' });
    }

    var tab = String(body.tab || 'aggregates');
    var headers = body.headers || [];
    var rows = body.rows || [];

    var book = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = book.getSheetByName(tab);
    if (!sheet) {
      // Create it rather than failing. Otherwise the first export dies and the fix is "go and add
      // a tab named exactly this by hand", which nobody remembers.
      sheet = book.insertSheet(tab);
    }

    // Header row, written once and kept in step if the columns ever change.
    var existing = sheet.getDataRange().getValues();
    if (existing.length === 0 || String(existing[0][0] || '') === '') {
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      sheet.setFrozenRows(1);
      existing = sheet.getDataRange().getValues();
    }

    // Column A is the stable key. Index what is already there so a re-export REPLACES a row
    // instead of appending a duplicate — the same idempotence guarantee the Cloud path gives.
    var keyToRow = {};
    for (var i = 1; i < existing.length; i++) {
      var key = String(existing[i][0] || '');
      if (key) keyToRow[key] = i + 1;   // 1-based sheet row
    }

    var written = 0;
    var skipped = 0;
    var appended = [];

    for (var r = 0; r < rows.length; r++) {
      var row = rows[r];
      var k = String(row[0]);
      if (keyToRow[k]) {
        var at = keyToRow[k];
        var current = sheet.getRange(at, 1, 1, headers.length).getValues()[0];
        if (sameRow(current, row, headers.length)) {
          skipped++;                     // already present and identical
        } else {
          sheet.getRange(at, 1, 1, headers.length).setValues([pad(row, headers.length)]);
          written++;
        }
      } else {
        appended.push(pad(row, headers.length));
        written++;
      }
    }

    // One write for everything new, rather than one per row. Per-row calls are what exhaust the
    // quota on a big export.
    if (appended.length) {
      sheet.getRange(sheet.getLastRow() + 1, 1, appended.length, headers.length)
           .setValues(appended);
    }

    return json({
      ok: true,
      rows_written: written,
      rows_skipped: skipped,
      spreadsheet_url: book.getUrl()
    });
  } catch (err) {
    return json({ ok: false, error: String(err) });
  }
}

/** A GET is useful for checking the deployment is live without writing anything. */
function doGet() {
  return json({ ok: true, service: 'tengen-sheets-export', note: 'POST rows to this URL' });
}

function pad(row, width) {
  var out = [];
  for (var i = 0; i < width; i++) out.push(i < row.length && row[i] != null ? row[i] : '');
  return out;
}

function sameRow(a, b, width) {
  for (var i = 0; i < width; i++) {
    var left = i < a.length && a[i] != null ? String(a[i]) : '';
    var right = i < b.length && b[i] != null ? String(b[i]) : '';
    if (left !== right) return false;
  }
  return true;
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
                       .setMimeType(ContentService.MimeType.JSON);
}
