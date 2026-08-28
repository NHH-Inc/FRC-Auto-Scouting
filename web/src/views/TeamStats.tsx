import { useMemo } from 'react';
import type { Job } from '../contracts';
import type { ViewEvent } from '../lib/corrections';
import { fmtPercent, fmtSeconds } from '../lib/format';
import { computeTeamStats, type TeamStats as Stats } from '../lib/stats';

// Doc 3: "Per-team aggregate stats across an event or a season."
//
// Every column is a query over the event list held in memory -- nothing here is stored, per
// doc 0's "Aggregates are never stored, only queried."
//
// Median cycle time leads because doc 3's scope section says so: "Per-robot cycle time
// alone is useful enough to hand to a drive team." Median rather than mean, because one
// immobile robot produces a single enormous interval that would drag an average.

export interface TeamStatsProps {
  job: Job;
  events: ViewEvent[];
  selectedTeam: number | null;
  onSelectTeam: (team: number | null) => void;
}

export function TeamStats({ job, events, selectedTeam, onSelectTeam }: TeamStatsProps) {
  const rows = useMemo(() => {
    const red = job.alliances?.red ?? [];
    const blue = job.alliances?.blue ?? [];
    return [
      ...red.map((t) => computeTeamStats(t, events, 'red')),
      ...blue.map((t) => computeTeamStats(t, events, 'blue')),
    ];
  }, [job.alliances, events]);

  const bestCycle = useMemo(() => {
    const xs = rows.map((r) => r.medianCycleSeconds).filter((x): x is number => x != null);
    return xs.length ? Math.min(...xs) : null;
  }, [rows]);

  if (rows.length === 0) {
    return (
      <div className="panel">
        <div className="panel-head"><h2>Team stats</h2></div>
        <p className="empty">
          No alliance data on this job. TBA had nothing for the match, so events cannot be
          grouped by team.
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Team stats</h2>
        <span className="muted">this match · computed from {events.length} events</span>
      </div>
      <div className="table-scroll">
        <table className="stats">
          <thead>
            <tr>
              <th>Team</th>
              <th title="Median seconds between consecutive reloads">Cycle (p50)</th>
              <th>Best</th>
              <th>Cycles</th>
              <th>Made</th>
              <th>Att.</th>
              <th>Acc.</th>
              <th title="Points contributed under the season config">Pts</th>
              <th>Defense</th>
              <th>Immobile</th>
              <th>Fouls</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <Row
                key={r.team}
                s={r}
                isBest={bestCycle != null && r.medianCycleSeconds === bestCycle}
                selected={r.team === selectedTeam}
                onClick={() => onSelectTeam(r.team === selectedTeam ? null : r.team)}
              />
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">
        A cycle is one acquire-to-acquire loop, measured between consecutive <code>reload</code>
        {' '}events — a missed shot still costs a cycle. Rows are clickable; selecting a team
        filters the heat map.
      </p>
    </div>
  );
}

function Row({
  s,
  isBest,
  selected,
  onClick,
}: {
  s: Stats;
  isBest: boolean;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <tr className={`${selected ? 'sel' : ''}`} onClick={onClick}>
      <td>
        <span className={`chip ${s.alliance ?? ''}`}>{s.team}</span>
      </td>
      <td className={isBest ? 'best' : ''}>{fmtSeconds(s.medianCycleSeconds)}</td>
      <td>{fmtSeconds(s.bestCycleSeconds)}</td>
      <td>{s.cycleCount}</td>
      <td>
        <strong>{s.shotsMade}</strong>
      </td>
      <td>{s.shotAttempts}</td>
      <td>{fmtPercent(s.accuracy)}</td>
      <td>{s.pointsContributed}</td>
      <td>{s.defenseSeconds > 0 ? fmtSeconds(s.defenseSeconds, 1) : '--'}</td>
      <td className={s.immobileSeconds > 0 ? 'warn' : ''}>
        {s.immobileSeconds > 0 ? fmtSeconds(s.immobileSeconds, 1) : '--'}
      </td>
      <td>{s.fouls > 0 ? s.fouls : '--'}</td>
    </tr>
  );
}
