import { useEffect, useMemo, useRef } from 'react';
import type { EventType } from '../contracts';
import type { ViewEvent } from '../lib/corrections';
import { EVENT_LABEL } from '../lib/format';
import { fieldExtents, type SeasonConfig } from '../season';

// Doc 3: "Field heat maps, once homography is working, showing where a robot spends time."
//
// Two honest limits, both surfaced in the UI rather than papered over:
//
//  1. This is event density, not dwell time. Field coordinates arrive on events, and Contract
//     C's boxes are image space, not field space -- component 3 has no homography of its own
//     and doc 0 is explicit that it must not invent one. So "where a robot scores from" is
//     answerable today; "where a robot spends time" needs field coordinates on track samples,
//     which is a contract change nobody has asked for yet.
//  2. field_x/field_y are null wherever homography failed. Those events are counted and
//     reported, never silently dropped.

const GRID_X = 72;
const GRID_Y = 36;
const SIGMA = 1.6; // grid cells

export interface HeatMapProps {
  season: SeasonConfig;
  events: ViewEvent[];
  selectedTeam: number | null;
  eventTypes?: EventType[];
}

export function HeatMap({
  season,
  events,
  selectedTeam,
  eventTypes = ['shot_made', 'shot_attempt'],
}: HeatMapProps) {
  const FIELD = fieldExtents(season);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const { points, missing } = useMemo(() => {
    const wanted = new Set(eventTypes);
    const pool = events.filter(
      (e) => wanted.has(e.eventType) && (selectedTeam == null || e.team === selectedTeam)
    );
    return {
      points: pool.filter((e) => e.fieldX != null && e.fieldY != null),
      missing: pool.filter((e) => e.fieldX == null || e.fieldY == null).length,
    };
  }, [events, selectedTeam, eventTypes]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth;
    const cssH = Math.round((cssW * FIELD.widthFt) / FIELD.lengthFt);
    canvas.style.height = `${cssH}px`;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    // Field. +x points at the blue alliance wall, so blue is on the right.
    ctx.fillStyle = '#171a21';
    ctx.fillRect(0, 0, cssW, cssH);
    ctx.fillStyle = 'rgba(224,85,95,0.10)';
    ctx.fillRect(0, 0, cssW * 0.16, cssH);
    ctx.fillStyle = 'rgba(76,140,240,0.10)';
    ctx.fillRect(cssW * 0.84, 0, cssW * 0.16, cssH);

    // Density grid with a small gaussian splat per event.
    const grid = new Float32Array(GRID_X * GRID_Y);
    const radius = Math.ceil(SIGMA * 2.5);
    for (const e of points) {
      const gx = ((e.fieldX! - FIELD.minX) / FIELD.lengthFt) * (GRID_X - 1);
      const gy = ((e.fieldY! - FIELD.minY) / FIELD.widthFt) * (GRID_Y - 1);
      const x0 = Math.max(0, Math.floor(gx - radius));
      const x1 = Math.min(GRID_X - 1, Math.ceil(gx + radius));
      const y0 = Math.max(0, Math.floor(gy - radius));
      const y1 = Math.min(GRID_Y - 1, Math.ceil(gy + radius));
      for (let y = y0; y <= y1; y++) {
        for (let x = x0; x <= x1; x++) {
          const d2 = (x - gx) ** 2 + (y - gy) ** 2;
          grid[y * GRID_X + x] += Math.exp(-d2 / (2 * SIGMA * SIGMA));
        }
      }
    }

    let peak = 0;
    for (const v of grid) if (v > peak) peak = v;
    if (peak > 0) {
      const cw = cssW / GRID_X;
      const ch = cssH / GRID_Y;
      for (let y = 0; y < GRID_Y; y++) {
        for (let x = 0; x < GRID_X; x++) {
          const v = grid[y * GRID_X + x] / peak;
          if (v < 0.02) continue;
          ctx.fillStyle = heatColour(v);
          ctx.fillRect(x * cw, y * ch, cw + 0.5, ch + 0.5);
        }
      }
    }

    // Field markings on top of the heat.
    ctx.strokeStyle = 'rgba(255,255,255,0.22)';
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, cssW - 1, cssH - 1);
    ctx.beginPath();
    ctx.moveTo(cssW / 2, 0);
    ctx.lineTo(cssW / 2, cssH);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cssW / 2, cssH / 2, Math.min(cssW, cssH) * 0.08, 0, Math.PI * 2);
    ctx.stroke();
  }, [points]);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Field heat map</h2>
        <span className="muted">
          {selectedTeam ? `team ${selectedTeam}` : 'all teams'} ·{' '}
          {eventTypes.map((t) => EVENT_LABEL[t].toLowerCase()).join(' + ')}
        </span>
      </div>
      <canvas ref={canvasRef} className="heatmap" />
      <div className="heat-axis">
        <span className="red">← red alliance wall</span>
        <span className="muted">field centre (0, 0) · scoring table side is +y, drawn lower</span>
        <span className="blue">blue alliance wall →</span>
      </div>
      <p className="note">
        {points.length} positioned {points.length === 1 ? 'event' : 'events'}
        {missing > 0 && (
          <>
            {' · '}
            <span className="warn">
              {missing} with no field position (homography failed for that frame range)
            </span>
          </>
        )}
        . Density of scoring events, not dwell time — field coordinates arrive on events, and
        Contract C boxes are image space.
      </p>
    </div>
  );
}

/** Dark blue -> cyan -> amber -> white. Perceptually rising, readable on a dark field. */
function heatColour(v: number): string {
  const stops: Array<[number, [number, number, number]]> = [
    [0.0, [30, 60, 130]],
    [0.35, [40, 160, 180]],
    [0.65, [232, 185, 59]],
    [1.0, [255, 245, 235]],
  ];
  let i = 0;
  while (i < stops.length - 2 && v > stops[i + 1][0]) i++;
  const [t0, c0] = stops[i];
  const [t1, c1] = stops[i + 1];
  const u = (v - t0) / (t1 - t0 || 1);
  const c = c0.map((ch, k) => Math.round(ch + (c1[k] - ch) * u));
  return `rgba(${c[0]},${c[1]},${c[2]},${0.25 + 0.65 * v})`;
}
