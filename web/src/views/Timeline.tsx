import { useMemo } from 'react';
import type { PlayableJob } from '../contracts';
import { phaseBounds, type SeasonConfig } from '../season';
import type { ViewEvent } from '../lib/corrections';
import { EVENT_LABEL, fmtTime } from '../lib/format';

// Doc 3: "Per-match timeline of events for all six robots."
//
// One lane per robot plus a lane for anything the model could not attribute, because an
// unattributed event is exactly what a reviewer needs to go find.

const ROW_H = 30;
const LABEL_W = 76;
const PAD = 10;

export interface TimelineProps {
  job: PlayableJob;
  season: SeasonConfig;
  events: ViewEvent[];
  confidenceThreshold: number;
  currentTime: number;
  selectedEventId: string | null;
  onSelectEvent: (eventId: string) => void;
  onSeek: (t: number) => void;
}

export function Timeline({
  job,
  season,
  events,
  confidenceThreshold,
  currentTime,
  selectedEventId,
  onSelectEvent,
  onSeek,
}: TimelineProps) {
  const lanes = useMemo(() => {
    const red = job.alliances?.red ?? [];
    const blue = job.alliances?.blue ?? [];
    const rows: Array<{ key: string; team: number | null; alliance: 'red' | 'blue' | null }> = [
      ...red.map((t) => ({ key: `r${t}`, team: t, alliance: 'red' as const })),
      ...blue.map((t) => ({ key: `b${t}`, team: t, alliance: 'blue' as const })),
    ];
    if (events.some((e) => e.team == null && e.trackId != null)) {
      rows.push({ key: 'unattributed', team: null, alliance: null });
    }
    return rows;
  }, [job.alliances, events]);

  const PHASE_BOUNDS = phaseBounds(season);

  const width = 900;
  const plotW = width - LABEL_W - PAD * 2;
  const height = lanes.length * ROW_H + 34;
  const xOf = (t: number) => LABEL_W + PAD + (t / job.duration) * plotW;

  // Match-level events get their own vertical rules across every lane.
  const rules = events.filter(
    (e) => e.eventType === 'match_start' || e.eventType === 'match_end' || e.eventType === 'phase_change'
  );

  const bands: Array<{ label: string; from: number; to: number; cls: string }> = [
    { label: 'auto', from: PHASE_BOUNDS.autoStart, to: PHASE_BOUNDS.autoEnd, cls: 'auto' },
    { label: 'teleop', from: PHASE_BOUNDS.autoEnd, to: PHASE_BOUNDS.teleopEnd, cls: 'teleop' },
    { label: 'endgame', from: PHASE_BOUNDS.teleopEnd, to: PHASE_BOUNDS.matchEnd, cls: 'endgame' },
  ];

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Match timeline</h2>
        <span className="muted">{events.length} events · click any mark to scrub there</span>
      </div>
      <div className="timeline-scroll">
        <svg
          className="timeline"
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          role="img"
          aria-label="Per-robot event timeline"
          onClick={(e) => {
            // Clicking empty plot area scrubs to that time.
            const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const px = ((e.clientX - rect.left) / rect.width) * width;
            if (px < LABEL_W + PAD) return;
            onSeek(((px - LABEL_W - PAD) / plotW) * job.duration);
          }}
        >
          {bands.map((b) => (
            <g key={b.label}>
              <rect
                className={`tl-band ${b.cls}`}
                x={xOf(b.from)}
                y={22}
                width={xOf(b.to) - xOf(b.from)}
                height={lanes.length * ROW_H}
              />
              <text className="tl-band-label" x={xOf(b.from) + 4} y={16}>
                {b.label}
              </text>
            </g>
          ))}

          {rules.map((r) => (
            <line
              key={r.eventId}
              className="tl-rule"
              x1={xOf(r.tSeconds)}
              x2={xOf(r.tSeconds)}
              y1={20}
              y2={22 + lanes.length * ROW_H}
            />
          ))}

          {lanes.map((lane, i) => {
            const y = 22 + i * ROW_H;
            const mine = events.filter((e) =>
              lane.team == null ? e.team == null && e.trackId != null : e.team === lane.team
            );
            return (
              <g key={lane.key}>
                <rect className="tl-lane" x={LABEL_W + PAD} y={y} width={plotW} height={ROW_H} />
                <text className={`tl-team ${lane.alliance ?? 'none'}`} x={PAD} y={y + ROW_H / 2 + 4}>
                  {lane.team ?? 'unattr.'}
                </text>
                {mine.map((e) => {
                  const low = e.confidence < confidenceThreshold;
                  const cx = xOf(e.tSeconds);
                  const cy = y + ROW_H / 2;
                  const on = e.eventId === selectedEventId;
                  const cls = `tl-mark ${e.eventType} ${low ? 'low' : ''} ${on ? 'on' : ''} ${e.corrected ? 'corrected' : ''}`;
                  const title = (
                    <title>
                      {`${EVENT_LABEL[e.eventType]} · ${fmtTime(e.tSeconds)} · conf ${e.confidence.toFixed(2)}${
                        e.corrected ? ' · corrected' : ''
                      }`}
                    </title>
                  );
                  const onClick = (ev: React.MouseEvent) => {
                    ev.stopPropagation();
                    onSelectEvent(e.eventId);
                    onSeek(e.tSeconds);
                  };
                  // Shape carries the event type so the row is readable without colour alone.
                  if (e.eventType === 'shot_made') {
                    return (
                      <circle key={e.eventId} className={cls} cx={cx} cy={cy} r={on ? 6 : 4.5} onClick={onClick}>
                        {title}
                      </circle>
                    );
                  }
                  if (e.eventType === 'shot_attempt') {
                    return (
                      <circle key={e.eventId} className={cls} cx={cx} cy={cy} r={on ? 5.5 : 4} onClick={onClick}>
                        {title}
                      </circle>
                    );
                  }
                  if (e.eventType === 'reload') {
                    return (
                      <rect key={e.eventId} className={cls} x={cx - 1.5} y={cy - 6} width={3} height={12} onClick={onClick}>
                        {title}
                      </rect>
                    );
                  }
                  return (
                    <rect
                      key={e.eventId}
                      className={cls}
                      x={cx - 4}
                      y={cy - 4}
                      width={8}
                      height={8}
                      transform={`rotate(45 ${cx} ${cy})`}
                      onClick={onClick}
                    >
                      {title}
                    </rect>
                  );
                })}
              </g>
            );
          })}

          <line
            className="tl-playhead"
            x1={xOf(currentTime)}
            x2={xOf(currentTime)}
            y1={18}
            y2={22 + lanes.length * ROW_H}
          />
        </svg>
      </div>
      <div className="legend">
        <span><i className="k shot_made" /> shot made</span>
        <span><i className="k shot_attempt" /> attempt</span>
        <span><i className="k reload" /> reload</span>
        <span><i className="k other" /> other</span>
        <span><i className="k low" /> below threshold</span>
        <span><i className="k corrected" /> corrected</span>
      </div>
    </div>
  );
}
