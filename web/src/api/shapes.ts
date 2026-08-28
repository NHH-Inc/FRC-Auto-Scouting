// ASSUMED RESPONSE SHAPES.
//
// Contract E names these three endpoints but never says what they return. Everything in
// this file is component 3 guessing, and every guess is listed in
// contracts/OPEN_QUESTIONS.md #6 so it gets settled rather than quietly ossifying.
//
// If component 2 returns something else, this is the only file that needs to change --
// the rest of web/ consumes the domain types below, not the wire shapes.

import type { ScoreBreakdown } from '../lib/stats';

// ---- GET /api/matches/:match_id/accuracy

export interface WireAccuracy {
  match_id: string;
  reconstructed: ScoreBreakdown;
  tba: ScoreBreakdown | null;
  delta: ScoreBreakdown | null;
}

export interface Accuracy {
  matchId: string;
  reconstructed: ScoreBreakdown;
  tba: ScoreBreakdown | null;
  delta: ScoreBreakdown | null;
}

export function parseAccuracy(raw: WireAccuracy): Accuracy {
  return {
    matchId: raw.match_id,
    reconstructed: raw.reconstructed,
    tba: raw.tba ?? null,
    delta: raw.delta ?? null,
  };
}

// ---- GET /api/teams/:team/stats?event_key=...
//
// Assumed to be the aggregate set component 3 already computes locally in lib/stats.ts, so
// the two paths render through the same component. Wire keys are snake_case per doc 0.

export interface WireTeamStats {
  team: number;
  event_key: string | null;
  matches_played: number;
  shot_attempts: number;
  shots_made: number;
  accuracy: number | null;
  reloads: number;
  cycle_count: number;
  median_cycle_seconds: number | null;
  best_cycle_seconds: number | null;
  defense_seconds: number;
  immobile_seconds: number;
  fouls: number;
  points_contributed: number;
}

export interface TeamStatsSummary {
  team: number;
  eventKey: string | null;
  matchesPlayed: number;
  shotAttempts: number;
  shotsMade: number;
  accuracy: number | null;
  reloads: number;
  cycleCount: number;
  medianCycleSeconds: number | null;
  bestCycleSeconds: number | null;
  defenseSeconds: number;
  immobileSeconds: number;
  fouls: number;
  pointsContributed: number;
}

export function parseTeamStats(raw: WireTeamStats): TeamStatsSummary {
  return {
    team: raw.team,
    eventKey: raw.event_key ?? null,
    matchesPlayed: raw.matches_played,
    shotAttempts: raw.shot_attempts,
    shotsMade: raw.shots_made,
    accuracy: raw.accuracy ?? null,
    reloads: raw.reloads,
    cycleCount: raw.cycle_count,
    medianCycleSeconds: raw.median_cycle_seconds ?? null,
    bestCycleSeconds: raw.best_cycle_seconds ?? null,
    defenseSeconds: raw.defense_seconds,
    immobileSeconds: raw.immobile_seconds,
    fouls: raw.fouls,
    pointsContributed: raw.points_contributed,
  };
}

// ---- POST /api/export/sheets
//
// The URL matters most: without it the UI cannot link the user to the sheet it just wrote.

export interface WireExportResult {
  spreadsheet_id: string;
  spreadsheet_url: string;
  rows_written: number;
  mode: 'raw' | 'aggregate';
  /** Doc 3 wants re-export to be idempotent, so a second run should report 0 new rows. */
  rows_updated?: number;
}

export interface ExportResult {
  spreadsheetId: string;
  spreadsheetUrl: string;
  rowsWritten: number;
  rowsUpdated: number;
  mode: 'raw' | 'aggregate';
}

export function parseExportResult(raw: WireExportResult): ExportResult {
  return {
    spreadsheetId: raw.spreadsheet_id,
    spreadsheetUrl: raw.spreadsheet_url,
    rowsWritten: raw.rows_written,
    rowsUpdated: raw.rows_updated ?? 0,
    mode: raw.mode,
  };
}
