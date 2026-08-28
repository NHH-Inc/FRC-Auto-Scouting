import { useState } from 'react';
import { getApi } from '../api';
import type { ExportResult } from '../api/shapes';

// Doc 3: "Sheets is an export destination, not storage." Component 3 does not talk to the
// Sheets API -- it POSTs to component 2, which owns the credentials and the batching.
//
// The mode choice is doc 3's: "Give users the choice of exporting raw events or aggregates,
// and make re-export idempotent so running it twice does not duplicate rows."

export interface ExportPanelProps {
  matchIds: string[];
}

export function ExportPanel({ matchIds }: ExportPanelProps) {
  const [mode, setMode] = useState<'raw' | 'aggregate'>('aggregate');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const api = await getApi();
      setResult(await api.exportSheets({ matchIds, mode }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Google Sheets export</h2>
        <span className="muted">
          {matchIds.length} {matchIds.length === 1 ? 'match' : 'matches'}
        </span>
      </div>

      <div className="export-modes">
        <label className={mode === 'aggregate' ? 'on' : ''}>
          <input
            type="radio"
            name="mode"
            checked={mode === 'aggregate'}
            onChange={() => setMode('aggregate')}
          />
          <span>
            <strong>Aggregates</strong>
            <span className="muted">
              One row per team per match, columns for the stats. The shape scouts actually
              use in a spreadsheet.
            </span>
          </span>
        </label>
        <label className={mode === 'raw' ? 'on' : ''}>
          <input type="radio" name="mode" checked={mode === 'raw'} onChange={() => setMode('raw')} />
          <span>
            <strong>Raw events</strong>
            <span className="muted">
              One row per event. Larger, but it is the source of truth and what a training
              export wants.
            </span>
          </span>
        </label>
      </div>

      <button type="button" className="primary" disabled={busy || matchIds.length === 0} onClick={run}>
        {busy ? 'Exporting…' : 'Export to Sheets'}
      </button>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="export-result">
          <p>
            Wrote <strong>{result.rowsWritten}</strong>{' '}
            {result.rowsWritten === 1 ? 'row' : 'rows'}
            {result.rowsUpdated > 0 && <> · updated {result.rowsUpdated} existing</>} in{' '}
            {result.mode} mode.
          </p>
          <a href={result.spreadsheetUrl} target="_blank" rel="noreferrer">
            Open spreadsheet ↗
          </a>
        </div>
      )}

      <p className="note">
        Re-exporting the same matches updates rows in place rather than appending, so running
        this twice does not duplicate anything. Writes are batched by the ingest service —
        per-row API calls hit the Sheets quota immediately.
      </p>
    </div>
  );
}
