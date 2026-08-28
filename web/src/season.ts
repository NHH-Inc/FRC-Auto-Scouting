// Season config. Doc 0: "Nominal field dimensions live in the season config, not in code."
//
// The config itself is in /contracts/ because component 1 needs the same numbers for
// homography and doc 0 forbids cross-imports between component directories. Reading from
// /contracts/ is not a cross-import -- that directory is explicitly shared.
// See contracts/OPEN_QUESTIONS.md #7.

import seasonJson from '../../contracts/season_2026.json';

export interface SeasonConfig {
  schemaVersion: number;
  season: number;
  field: { lengthFt: number; widthFt: number };
  periods: { autoSeconds: number; teleopSeconds: number; endgameSeconds: number };
  scoring: {
    shotMade: { auto: number; teleop: number; endgame: number };
    foulPointsToOpponent: number;
  };
}

export const SEASON: SeasonConfig = {
  schemaVersion: seasonJson.schema_version,
  season: seasonJson.season,
  field: { lengthFt: seasonJson.field.length_ft, widthFt: seasonJson.field.width_ft },
  periods: {
    autoSeconds: seasonJson.periods.auto_seconds,
    teleopSeconds: seasonJson.periods.teleop_seconds,
    endgameSeconds: seasonJson.periods.endgame_seconds,
  },
  scoring: {
    shotMade: seasonJson.scoring.shot_made,
    foulPointsToOpponent: seasonJson.scoring.foul_points_to_opponent,
  },
};

/**
 * Phase boundaries in segment time, measured from match_start.
 * Endgame is the final endgameSeconds of teleop, not a fourth period.
 */
export const PHASE_BOUNDS = {
  autoStart: 0,
  autoEnd: SEASON.periods.autoSeconds,
  teleopEnd:
    SEASON.periods.autoSeconds + SEASON.periods.teleopSeconds - SEASON.periods.endgameSeconds,
  matchEnd: SEASON.periods.autoSeconds + SEASON.periods.teleopSeconds,
};

/** Field extents in feet. Origin is field centre, so these are symmetric. */
export const FIELD = {
  minX: -SEASON.field.lengthFt / 2,
  maxX: SEASON.field.lengthFt / 2,
  minY: -SEASON.field.widthFt / 2,
  maxY: SEASON.field.widthFt / 2,
  lengthFt: SEASON.field.lengthFt,
  widthFt: SEASON.field.widthFt,
};
