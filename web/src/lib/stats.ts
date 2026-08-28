// Aggregates.
//
// Doc 0: "Aggregates are never stored, only queried." Doc 3: "Never store aggregates as
// primary data. Every stat is a query over the event table." So every number below is
// derived on demand from a ScoutEvent[] and nothing here is ever persisted or cached to
// disk. In fixture mode these run in the browser; against a real backend the same shapes
// come from GET /api/teams/:team/stats.

import type { Alliance, EventType, Phase, ScoutEvent } from '../contracts';
import { SEASON, PHASE_BOUNDS } from '../season';

export interface TeamStats {
  team: number;
  alliance: Alliance | null;
  shotAttempts: number;
  shotsMade: number;
  /** Made / attempted. null when the team never attempted a shot. */
  accuracy: number | null;
  reloads: number;
  /**
   * Doc 3: "Per-robot cycle time alone is useful enough to hand to a drive team."
   * A cycle is one acquire-to-acquire loop, measured between consecutive `reload` events.
   * Reload is the anchor rather than a shot because a missed shot should still cost a cycle.
   */
  cycleCount: number;
  medianCycleSeconds: number | null;
  bestCycleSeconds: number | null;
  cycleSeconds: number[];
  defenseSeconds: number;
  immobileSeconds: number;
  fouls: number;
  /** Points this team's made shots are worth under the season config. */
  pointsContributed: number;
  byPhase: Record<Phase, { attempts: number; made: number }>;
}

const EMPTY_PHASES = (): Record<Phase, { attempts: number; made: number }> => ({
  auto: { attempts: 0, made: 0 },
  teleop: { attempts: 0, made: 0 },
  endgame: { attempts: 0, made: 0 },
  unknown: { attempts: 0, made: 0 },
});

function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/**
 * Total seconds spanned by start/end pairs of the given types.
 * An unclosed interval is held open to `matchEnd` rather than dropped -- a robot that goes
 * immobile and never recovers was immobile for the rest of the match.
 */
function pairedSeconds(
  events: ScoutEvent[],
  startType: EventType,
  endType: EventType,
  matchEnd: number
): number {
  let total = 0;
  let openedAt: number | null = null;
  for (const e of events) {
    if (e.eventType === startType && openedAt === null) openedAt = e.tSeconds;
    else if (e.eventType === endType && openedAt !== null) {
      total += Math.max(0, e.tSeconds - openedAt);
      openedAt = null;
    }
  }
  if (openedAt !== null) total += Math.max(0, matchEnd - openedAt);
  return total;
}

export function computeTeamStats(
  team: number,
  allEvents: ScoutEvent[],
  alliance: Alliance | null = null,
  matchEnd: number = PHASE_BOUNDS.matchEnd
): TeamStats {
  const mine = allEvents
    .filter((e) => e.team === team)
    .sort((a, b) => a.tSeconds - b.tSeconds);

  const byPhase = EMPTY_PHASES();
  let shotAttempts = 0;
  let shotsMade = 0;
  let reloads = 0;
  let fouls = 0;
  let pointsContributed = 0;
  const reloadTimes: number[] = [];

  for (const e of mine) {
    switch (e.eventType) {
      case 'shot_attempt':
        shotAttempts++;
        byPhase[e.phase].attempts++;
        break;
      case 'shot_made':
        shotsMade++;
        byPhase[e.phase].made++;
        pointsContributed += pointsFor(e.phase);
        break;
      case 'reload':
        reloads++;
        reloadTimes.push(e.tSeconds);
        break;
      case 'foul':
        fouls++;
        break;
      default:
        break;
    }
  }

  const cycleSeconds: number[] = [];
  for (let i = 1; i < reloadTimes.length; i++) {
    cycleSeconds.push(reloadTimes[i] - reloadTimes[i - 1]);
  }

  return {
    team,
    alliance,
    shotAttempts,
    shotsMade,
    accuracy: shotAttempts > 0 ? shotsMade / shotAttempts : null,
    reloads,
    cycleCount: cycleSeconds.length,
    medianCycleSeconds: median(cycleSeconds),
    bestCycleSeconds: cycleSeconds.length ? Math.min(...cycleSeconds) : null,
    cycleSeconds,
    defenseSeconds: pairedSeconds(mine, 'defense_start', 'defense_end', matchEnd),
    immobileSeconds: pairedSeconds(mine, 'immobile_start', 'immobile_end', matchEnd),
    fouls,
    pointsContributed,
    byPhase,
  };
}

export function pointsFor(phase: Phase): number {
  if (phase === 'auto') return SEASON.scoring.shotMade.auto;
  if (phase === 'teleop') return SEASON.scoring.shotMade.teleop;
  if (phase === 'endgame') return SEASON.scoring.shotMade.endgame;
  return 0;
}

export interface ScoreBreakdown {
  red: number;
  blue: number;
}

/**
 * Reconstruct the match score from events, for the "reconstructed vs TBA" indicator doc 3
 * asks for. Events with a null team contribute nothing -- an unidentified robot cannot be
 * credited to an alliance, and guessing would quietly inflate the accuracy number.
 */
export function reconstructScore(
  events: ScoutEvent[],
  alliances: { red: number[]; blue: number[] } | null
): ScoreBreakdown {
  const out: ScoreBreakdown = { red: 0, blue: 0 };
  if (!alliances) return out;
  const sideOf = (team: number | null): Alliance | null => {
    if (team == null) return null;
    if (alliances.red.includes(team)) return 'red';
    if (alliances.blue.includes(team)) return 'blue';
    return null;
  };
  for (const e of events) {
    const side = sideOf(e.team);
    if (!side) continue;
    if (e.eventType === 'shot_made') out[side] += pointsFor(e.phase);
    if (e.eventType === 'foul') {
      out[side === 'red' ? 'blue' : 'red'] += SEASON.scoring.foulPointsToOpponent;
    }
  }
  return out;
}

export interface AccuracyReport {
  reconstructed: ScoreBreakdown;
  tba: ScoreBreakdown | null;
  delta: ScoreBreakdown | null;
  /** Mean absolute error across both alliances, in points. null without a TBA score. */
  meanAbsError: number | null;
}

export function accuracyReport(
  events: ScoutEvent[],
  alliances: { red: number[]; blue: number[] } | null,
  tba: ScoreBreakdown | null
): AccuracyReport {
  const reconstructed = reconstructScore(events, alliances);
  if (!tba) return { reconstructed, tba: null, delta: null, meanAbsError: null };
  const delta = { red: reconstructed.red - tba.red, blue: reconstructed.blue - tba.blue };
  return {
    reconstructed,
    tba,
    delta,
    meanAbsError: (Math.abs(delta.red) + Math.abs(delta.blue)) / 2,
  };
}

/** Roll per-match team stats up across an event or a season. */
export function mergeTeamStats(rows: TeamStats[]): TeamStats | null {
  if (rows.length === 0) return null;
  const cycleSeconds = rows.flatMap((r) => r.cycleSeconds);
  const shotAttempts = rows.reduce((n, r) => n + r.shotAttempts, 0);
  const shotsMade = rows.reduce((n, r) => n + r.shotsMade, 0);
  const byPhase = EMPTY_PHASES();
  for (const r of rows) {
    for (const p of Object.keys(byPhase) as Phase[]) {
      byPhase[p].attempts += r.byPhase[p].attempts;
      byPhase[p].made += r.byPhase[p].made;
    }
  }
  return {
    team: rows[0].team,
    alliance: rows[0].alliance,
    shotAttempts,
    shotsMade,
    accuracy: shotAttempts > 0 ? shotsMade / shotAttempts : null,
    reloads: rows.reduce((n, r) => n + r.reloads, 0),
    cycleCount: cycleSeconds.length,
    medianCycleSeconds: median(cycleSeconds),
    bestCycleSeconds: cycleSeconds.length ? Math.min(...cycleSeconds) : null,
    cycleSeconds,
    defenseSeconds: rows.reduce((n, r) => n + r.defenseSeconds, 0),
    immobileSeconds: rows.reduce((n, r) => n + r.immobileSeconds, 0),
    fouls: rows.reduce((n, r) => n + r.fouls, 0),
    pointsContributed: rows.reduce((n, r) => n + r.pointsContributed, 0),
    byPhase,
  };
}
