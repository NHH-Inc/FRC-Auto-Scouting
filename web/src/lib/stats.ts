// Aggregates.
//
// Doc 0: "Aggregates are never stored, only queried." Every number below is derived on demand
// from a ScoutEvent[]; nothing here is persisted or cached.

import type { Alliance, EventType, Phase, ScoutEvent } from '../contracts';
import { phaseBounds, pointValuesArePlaceholders, type SeasonConfig } from '../season';

export interface ScoreBreakdown { red: number; blue: number }

export interface TeamStats {
  team: number;
  alliance: Alliance | null;
  shotAttempts: number;
  shotsMade: number;
  /** Made / attempted. Null when the team never attempted a shot. */
  accuracy: number | null;
  reloads: number;
  /**
   * Doc 0's vocabulary: "the interval between one `reload` event and the next `reload` event
   * for the same team. Acquire to acquire, not acquire to score, so a missed shot still costs
   * a cycle... An unterminated final cycle is discarded, not counted."
   */
  cycleCount: number;
  medianCycleSeconds: number | null;
  bestCycleSeconds: number | null;
  cycleSeconds: number[];
  /** Doc 1: "Shot rate: interval between consecutive shot events." */
  avgShotIntervalSeconds: number | null;
  defenseSeconds: number;
  immobileSeconds: number;
  fouls: number;
  pointsContributed: number;
  lowConfidenceEvents: number;
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

function mean(xs: number[]): number | null {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

/**
 * Points for one made shot in a phase, at a given goal.
 *
 * v3 added `goal`, so this no longer has to assume every shot went in the high goal. A null
 * goal means the model could not place the shot -- it scores 0 rather than guessing, which
 * keeps the accuracy comparison honest about what the pipeline actually knows.
 *
 * All point values are zero placeholders until the game is public; doc 0: "Do not invent
 * values to make a test pass."
 */
export function pointsFor(phase: Phase, goal: string | null, cfg: SeasonConfig | null): number {
  if (!cfg || !goal) return 0;
  const group = cfg.pointValues[phase];
  if (!group) return 0;
  return group[`shot_made_${goal}`] ?? 0;
}

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
  cfg: SeasonConfig | null = null,
  lowConfidenceThreshold = 0.5
): TeamStats {
  const matchEnd = cfg ? phaseBounds(cfg).matchEnd : Infinity;
  const mine = allEvents.filter((e) => e.team === team).sort((a, b) => a.tSeconds - b.tSeconds);

  const byPhase = EMPTY_PHASES();
  let shotAttempts = 0;
  let shotsMade = 0;
  let reloads = 0;
  let fouls = 0;
  let pointsContributed = 0;
  let lowConfidenceEvents = 0;
  const reloadTimes: number[] = [];
  const shotTimes: number[] = [];

  for (const e of mine) {
    if (e.confidence < lowConfidenceThreshold) lowConfidenceEvents++;
    switch (e.eventType) {
      case 'shot_attempt':
        shotAttempts++;
        shotTimes.push(e.tSeconds);
        byPhase[e.phase].attempts++;
        break;
      case 'shot_made':
        shotsMade++;
        byPhase[e.phase].made++;
        pointsContributed += pointsFor(e.phase, e.goal, cfg);
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

  // Acquire-to-acquire. An unterminated final cycle is simply never formed, since a cycle
  // only exists between two reloads.
  const cycleSeconds: number[] = [];
  for (let i = 1; i < reloadTimes.length; i++) {
    cycleSeconds.push(reloadTimes[i] - reloadTimes[i - 1]);
  }
  const shotIntervals: number[] = [];
  for (let i = 1; i < shotTimes.length; i++) shotIntervals.push(shotTimes[i] - shotTimes[i - 1]);

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
    avgShotIntervalSeconds: mean(shotIntervals),
    defenseSeconds: pairedSeconds(mine, 'defense_start', 'defense_end', matchEnd),
    immobileSeconds: pairedSeconds(mine, 'immobile_start', 'immobile_end', matchEnd),
    fouls,
    pointsContributed,
    lowConfidenceEvents,
    byPhase,
  };
}

/**
 * Reconstruct the match score from events, for the "reconstructed vs TBA" indicator.
 *
 * Events with a null team contribute nothing -- an unidentified robot cannot be credited to
 * an alliance, and guessing would quietly inflate the accuracy number this exists to test.
 */
export function reconstructScore(
  events: ScoutEvent[],
  alliances: { red: number[]; blue: number[] } | null,
  cfg: SeasonConfig | null
): ScoreBreakdown {
  const out: ScoreBreakdown = { red: 0, blue: 0 };
  if (!alliances || !cfg) return out;
  const sideOf = (team: number | null): Alliance | null => {
    if (team == null) return null;
    if (alliances.red.includes(team)) return 'red';
    if (alliances.blue.includes(team)) return 'blue';
    return null;
  };
  for (const e of events) {
    const side = sideOf(e.team);
    if (!side) continue;
    if (e.eventType === 'shot_made') out[side] += pointsFor(e.phase, e.goal, cfg);
  }
  return out;
}

/** Whether a reconstructed score means anything yet. */
export function scoringIsMeaningful(cfg: SeasonConfig | null): boolean {
  return cfg != null && !pointValuesArePlaceholders(cfg);
}
