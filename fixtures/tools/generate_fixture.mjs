// Regenerates fixtures/2026casf_qm42/ -- the one fully worked example doc 0 asks for.
//
// Deterministic: same seed in, byte-identical JSON out. Run with:
//     node fixtures/tools/generate_fixture.mjs
// Requires ffmpeg on PATH for segment.mp4 (pass --no-video to skip).
//
// The synthetic match is authored here rather than hand-typed so that the video, the
// tracks and the events are guaranteed to agree: robot positions come from one motion
// model, the video renders that model at 30 fps, tracks.jsonl samples it at 5 Hz, and
// events.jsonl is emitted from the same schedule. If a box in the UI does not sit on the
// robot under it, that is a real bug in component 3, not fixture drift.

import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');
const OUT = resolve(ROOT, 'fixtures', '2026casf_qm42');
const SEASON = JSON.parse(readFileSync(resolve(ROOT, 'contracts', 'season_2026.json'), 'utf8'));

// ---------------------------------------------------------------- constants

const JOB_ID = 'f81d4fae-7dec-11d0-a765-00a0c91e6bf6';
const MATCH_ID = '2026casf_qm42';
const VIDEO_ID = 'dQw4w9WgXcQ';
const START_OFFSET = 120.0; // segment was clipped out of a long event stream
const DURATION = 152.0;
const FPS = 30;
const W = 640;
const H = 360;
const BOX_HZ = 5; // deliberately != FPS so component 3 must interpolate

const FIELD_L = SEASON.field.length_ft; // 54
const FIELD_W = SEASON.field.width_ft; // 27
const T_AUTO_END = SEASON.periods.auto_seconds; // 15
const T_ENDGAME =
  T_AUTO_END + SEASON.periods.teleop_seconds - SEASON.periods.endgame_seconds; // 130
const T_MATCH_END = T_AUTO_END + SEASON.periods.teleop_seconds; // 150

// mulberry32, so the fixture is reproducible
function makeRng(seed) {
  let s = seed >>> 0;
  return function next() {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = makeRng(0x5f3a71c9);
const jitter = (a) => (rnd() * 2 - 1) * a;
const r3 = (n) => Math.round(n * 1000) / 1000;
const r2 = (n) => Math.round(n * 100) / 100;
const smooth = (u) => u * u * (3 - 2 * u);
const clamp01 = (u) => (u < 0 ? 0 : u > 1 ? 1 : u);

// +x is toward the BLUE alliance wall, so red robots load near x = -22 and score near x = +15.
const ROBOTS = [
  { team: 254, track_id: 7, alliance: 'red', cycle: 8.5, acc: 0.86, lane: -7.5 },
  { team: 1678, track_id: 3, alliance: 'red', cycle: 10.2, acc: 0.77, lane: 0.0 },
  { team: 971, track_id: 11, alliance: 'red', cycle: 12.6, acc: 0.61, lane: 7.5 },
  { team: 118, track_id: 5, alliance: 'blue', cycle: 9.1, acc: 0.81, lane: -4.0 },
  { team: 148, track_id: 9, alliance: 'blue', cycle: 11.3, acc: 0.7, lane: 3.5 },
  { team: 2056, track_id: 2, alliance: 'blue', cycle: 13.4, acc: 0.65, lane: 10.5 },
];
const UNKNOWN_TRACK = { team: null, track_id: 14, from: 88.0, to: 96.0 };

// narrative beats, so the fixture exercises more than the happy path
const IMMOBILE = { team: 971, from: 72.4, to: 95.1 };
const DEFENSE = { team: 2056, from: 40.2, to: 70.6, target: 254 };
const HOMOGRAPHY_GAP = { from: 100.0, to: 110.0 }; // field_x/field_y null in here
const FOUL = { team: 148, t: 118.35 };

// ---------------------------------------------------------------- motion

// Each robot shuttles between a loading point near its own wall and a scoring point on
// the far side. One cycle = travel out, shoot, travel back, reload.
function buildSchedule(r) {
  const sign = r.alliance === 'red' ? -1 : 1;
  const load = { x: sign * 22.5, y: r.lane * 0.55 };
  const score = { x: -sign * 15.0, y: r.lane };
  const legs = [];
  let t = 0;
  let leg = 0;
  while (t < DURATION) {
    const c = Math.max(4.5, r.cycle + jitter(r.cycle * 0.16));
    const travel = c * 0.4;
    const dwell = c * 0.1;
    const outbound = leg % 2 === 0;
    legs.push({
      t0: t,
      t1: t + travel,
      from: outbound ? load : score,
      to: outbound ? score : load,
      kind: 'travel',
    });
    t += travel;
    const at = outbound ? score : load;
    legs.push({
      t0: t,
      t1: t + dwell,
      from: at,
      to: at,
      kind: 'dwell',
      action: outbound ? 'shoot' : 'reload',
    });
    t += dwell;
    leg++;
  }
  return legs;
}
const SCHED = new Map(ROBOTS.map((r) => [r.team, buildSchedule(r)]));

function basePos(team, t) {
  const legs = SCHED.get(team);
  let lo = 0;
  let hi = legs.length - 1;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (legs[m].t1 <= t) lo = m + 1;
    else hi = m;
  }
  const l = legs[lo];
  const u = l.kind === 'dwell' ? 1 : smooth(clamp01((t - l.t0) / (l.t1 - l.t0)));
  return { x: l.from.x + (l.to.x - l.from.x) * u, y: l.from.y + (l.to.y - l.from.y) * u };
}

// Position with the narrative beats layered on top.
function pos(team, t) {
  if (team === IMMOBILE.team && t >= IMMOBILE.from && t <= IMMOBILE.to) {
    return basePos(team, IMMOBILE.from);
  }
  if (team === DEFENSE.team && t >= DEFENSE.from && t <= DEFENSE.to) {
    const p = pos(DEFENSE.target, t);
    return { x: p.x + 3.1, y: p.y + 2.4 }; // shadowing, a bumper-width away
  }
  return basePos(team, t);
}
function unknownPos(t) {
  const u = clamp01((t - UNKNOWN_TRACK.from) / (UNKNOWN_TRACK.to - UNKNOWN_TRACK.from));
  return { x: -24.5 + u * 6.0, y: 11.6 - u * 1.2 };
}

// Field space -> normalized image space. Camera sits on the scoring-table side (+y), so
// larger y is nearer the camera: lower on screen and a slightly larger box.
function project(p) {
  const u = 0.5 + (p.x / FIELD_L) * 0.86;
  const v = 0.52 + (p.y / FIELD_W) * 0.62;
  const s = 1 + 0.35 * (p.y / (FIELD_W / 2));
  const w = 0.055 * s;
  const h = 0.075 * s;
  return { x: u - w / 2, y: v - h / 2, w, h };
}

// ---------------------------------------------------------------- events

const phaseAt = (t) => (t < T_AUTO_END ? 'auto' : t < T_ENDGAME ? 'teleop' : 'endgame');
const suppressed = (team, t) =>
  (team === IMMOBILE.team && t >= IMMOBILE.from && t <= IMMOBILE.to) ||
  (team === DEFENSE.team && t >= DEFENSE.from && t <= DEFENSE.to);

const events = [];
const byTeam = (n) => ROBOTS.find((r) => r.team === n);

function mk(t, type, team, trackId, conf, opts) {
  const o = opts || {};
  const p = team == null ? o.pos || null : pos(team, t);
  const blind = t >= HOMOGRAPHY_GAP.from && t <= HOMOGRAPHY_GAP.to;
  return {
    schema_version: 1,
    job_id: JOB_ID,
    match_id: MATCH_ID,
    event_id: '', // assigned after sort
    team,
    track_id: trackId,
    t_seconds: r3(t),
    phase: phaseAt(t),
    event_type: type,
    confidence: r2(Math.min(0.99, Math.max(0.05, conf))),
    field_x: blind || !p ? null : r2(p.x),
    field_y: blind || !p ? null : r2(p.y),
    source: o.source || 'model',
  };
}

// match-level events. No track to attribute them to -- see contracts/OPEN_QUESTIONS.md #1.
events.push(mk(0.0, 'match_start', null, null, 0.98, { source: 'scoreboard_ocr' }));
events.push(mk(T_AUTO_END, 'phase_change', null, null, 0.97, { source: 'scoreboard_ocr' }));
events.push(mk(T_ENDGAME, 'phase_change', null, null, 0.95, { source: 'scoreboard_ocr' }));
events.push(mk(T_MATCH_END, 'match_end', null, null, 0.98, { source: 'scoreboard_ocr' }));

for (const r of ROBOTS) {
  for (const leg of SCHED.get(r.team)) {
    if (leg.kind !== 'dwell') continue;
    const t = leg.t0 + (leg.t1 - leg.t0) * 0.5;
    if (t > T_MATCH_END || suppressed(r.team, t)) continue;
    if (leg.action === 'reload') {
      events.push(mk(t, 'reload', r.team, r.track_id, 0.74 + jitter(0.14)));
    } else {
      events.push(mk(t, 'shot_attempt', r.team, r.track_id, 0.8 + jitter(0.16)));
      if (rnd() < r.acc) {
        events.push(mk(t + 0.28, 'shot_made', r.team, r.track_id, 0.7 + jitter(0.22)));
      }
    }
  }
}

events.push(mk(IMMOBILE.from, 'immobile_start', 971, byTeam(971).track_id, 0.66));
events.push(mk(IMMOBILE.to, 'immobile_end', 971, byTeam(971).track_id, 0.59));
events.push(mk(DEFENSE.from, 'defense_start', 2056, byTeam(2056).track_id, 0.52));
events.push(mk(DEFENSE.to, 'defense_end', 2056, byTeam(2056).track_id, 0.47));
events.push(mk(FOUL.t, 'foul', 148, byTeam(148).track_id, 0.41, { source: 'scoreboard_ocr' }));
// an unidentified track the model could not resolve to a team
events.push(
  mk(91.2, 'shot_attempt', null, UNKNOWN_TRACK.track_id, 0.29, { pos: unknownPos(91.2) })
);

events.sort((a, b) => a.t_seconds - b.t_seconds || a.event_type.localeCompare(b.event_type));
events.forEach((e, i) => {
  e.event_id = JOB_ID.slice(0, 8) + '-' + String(i).padStart(4, '0');
});

// ---------------------------------------------------------------- tracks

function sampleBoxes(fn, from, to) {
  const out = [];
  const step = 1 / BOX_HZ;
  for (let i = 0; ; i++) {
    const t = from + i * step;
    if (t > to + 1e-9) break;
    const b = project(fn(t));
    out.push({ t: r3(t), x: r3(b.x), y: r3(b.y), w: r3(b.w), h: r3(b.h) });
  }
  return out;
}
const tracks = ROBOTS.map((r) => ({
  schema_version: 1,
  track_id: r.track_id,
  team: r.team,
  alliance: r.alliance,
  boxes: sampleBoxes((t) => pos(r.team, t), 0, DURATION),
}));
tracks.push({
  schema_version: 1,
  track_id: UNKNOWN_TRACK.track_id,
  team: null,
  alliance: null,
  boxes: sampleBoxes(unknownPos, UNKNOWN_TRACK.from, UNKNOWN_TRACK.to),
});
tracks.sort((a, b) => a.track_id - b.track_id);

// ---------------------------------------------------------------- score

const PTS = SEASON.scoring.shot_made;
const recon = { red: 0, blue: 0 };
for (const e of events) {
  if (e.event_type === 'shot_made' && e.team != null) {
    recon[byTeam(e.team).alliance] += PTS[e.phase] || 0;
  }
  if (e.event_type === 'foul' && e.team != null) {
    const other = byTeam(e.team).alliance === 'red' ? 'blue' : 'red';
    recon[other] += SEASON.scoring.foul_points_to_opponent;
  }
}
// TBA is ground truth and will not match exactly -- that gap is the accuracy indicator.
const TBA = { red: recon.red + 7, blue: recon.blue - 4 };

// ---------------------------------------------------------------- write

mkdirSync(OUT, { recursive: true });
const jsonl = (rows) => rows.map((r) => JSON.stringify(r)).join('\n') + '\n';
const json = (o) => JSON.stringify(o, null, 2) + '\n';
const teamsOf = (a) => ROBOTS.filter((r) => r.alliance === a).map((r) => r.team);

writeFileSync(
  resolve(OUT, 'job.json'),
  json({
    schema_version: 1,
    job_id: JOB_ID,
    match_id: MATCH_ID,
    video_id: VIDEO_ID,
    local_path: '/data/segments/' + VIDEO_ID + '_00120_00272.mp4',
    start_offset: START_OFFSET,
    duration: DURATION,
    fps: FPS,
    width: W,
    height: H,
    status: 'complete',
    alliances: { red: teamsOf('red'), blue: teamsOf('blue') },
    tba_score: TBA,
  })
);
writeFileSync(resolve(OUT, 'events.jsonl'), jsonl(events));
writeFileSync(resolve(OUT, 'tracks.jsonl'), jsonl(tracks));
writeFileSync(
  resolve(OUT, 'result.json'),
  json({
    schema_version: 1,
    box_sample_rate: BOX_HZ,
    homography_ok: true,
    reconstructed_score: recon,
    frames_analyzed: Math.round(DURATION * FPS) - 118,
    frames_skipped_shot_change: 118,
    model_version: 'fixture-synthetic-0.1.0',
  })
);

// Snapshot of the TBA response, with frcNNN keys intact: this is the boundary where
// component 2 strips the prefix, and the fixture should show the raw form.
writeFileSync(
  resolve(OUT, 'tba_match.json'),
  json({
    key: MATCH_ID,
    comp_level: 'qm',
    set_number: 1,
    match_number: 42,
    event_key: '2026casf',
    winning_alliance: TBA.red > TBA.blue ? 'red' : 'blue',
    alliances: {
      red: {
        score: TBA.red,
        team_keys: teamsOf('red').map((t) => 'frc' + t),
        surrogate_team_keys: [],
        dq_team_keys: [],
      },
      blue: {
        score: TBA.blue,
        team_keys: teamsOf('blue').map((t) => 'frc' + t),
        surrogate_team_keys: [],
        dq_team_keys: [],
      },
    },
    time: 1774028400,
    actual_time: 1774028733,
    predicted_time: 1774028400,
    post_result_time: 1774028901,
    score_breakdown: null,
    videos: [{ type: 'youtube', key: VIDEO_ID + '?t=' + Math.round(START_OFFSET) }],
  })
);

// Corrections layer. Not one of the five artifacts doc 0 lists, but component 3 cannot
// demonstrate the corrections view without one. See fixtures/README.md.
const lowConf = events.find((e) => e.team === null && e.event_type === 'shot_attempt');
const falsePos = events.find((e) => e.event_type === 'shot_made' && e.confidence < 0.55);
writeFileSync(
  resolve(OUT, 'corrections.jsonl'),
  jsonl([
    {
      correction_id: '9a1c0e42-1f3b-4d55-9c8a-2b7e5f0a1d33',
      event_id: lowConf.event_id,
      action: 'edit',
      fields: { team: 971, track_id: byTeam(971).track_id },
      created_at: '2026-08-28T14:22:00Z',
    },
    {
      correction_id: 'c47d1b90-6e28-4a71-83f0-5d9a2c4e6b11',
      event_id: falsePos.event_id,
      action: 'delete',
      fields: null,
      created_at: '2026-08-28T14:23:12Z',
    },
    {
      correction_id: 'e02f7a35-8c14-49d6-b7a2-0f3e8d1c9a44',
      event_id: JOB_ID.slice(0, 8) + '-m001',
      action: 'create',
      fields: {
        team: 1678,
        track_id: byTeam(1678).track_id,
        t_seconds: 63.5,
        phase: 'teleop',
        event_type: 'shot_made',
        confidence: 1.0,
        field_x: null,
        field_y: null,
        source: 'manual',
      },
      created_at: '2026-08-28T14:25:47Z',
    },
  ])
);

console.log(
  'events=' + events.length + ' tracks=' + tracks.length +
  ' recon=' + JSON.stringify(recon) + ' tba=' + JSON.stringify(TBA)
);

// ---------------------------------------------------------------- video

if (process.argv.includes('--no-video')) {
  console.log('skipped segment.mp4 (--no-video)');
  process.exit(0);
}

// 3x5 bitmap digits, so a human can check that the overlay label matches the bumper.
const GLYPHS = {
  0: [7, 5, 5, 5, 7], 1: [2, 6, 2, 2, 7], 2: [7, 1, 7, 4, 7], 3: [7, 1, 7, 1, 7],
  4: [5, 5, 7, 1, 1], 5: [7, 4, 7, 1, 7], 6: [7, 4, 7, 5, 7], 7: [7, 1, 1, 1, 1],
  8: [7, 5, 7, 5, 7], 9: [7, 5, 7, 1, 7],
};

const frame = Buffer.alloc(W * H * 3);
function px(x, y, r, g, b) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  const i = (y * W + x) * 3;
  frame[i] = r;
  frame[i + 1] = g;
  frame[i + 2] = b;
}
function rect(x0, y0, w, h, r, g, b) {
  const xs = Math.max(0, Math.round(x0));
  const ys = Math.max(0, Math.round(y0));
  const xe = Math.min(W, Math.round(x0 + w));
  const ye = Math.min(H, Math.round(y0 + h));
  for (let y = ys; y < ye; y++) for (let x = xs; x < xe; x++) px(x, y, r, g, b);
}
function digits(text, x0, y0, scale, r, g, b) {
  let cx = x0;
  for (const ch of text) {
    const rows = GLYPHS[ch];
    if (rows) {
      for (let ry = 0; ry < 5; ry++) {
        for (let rx = 0; rx < 3; rx++) {
          if ((rows[ry] >> (2 - rx)) & 1) rect(cx + rx * scale, y0 + ry * scale, scale, scale, r, g, b);
        }
      }
    }
    cx += 4 * scale;
  }
}

function drawFrame(t) {
  rect(0, 0, W, H, 26, 29, 36); // carpet
  // field carpet band + alliance zone tints, drawn in image space via project()
  const topLeft = project({ x: -FIELD_L / 2, y: -FIELD_W / 2 });
  const botRight = project({ x: FIELD_L / 2, y: FIELD_W / 2 });
  const fx0 = topLeft.x * W;
  const fy0 = topLeft.y * H;
  const fx1 = botRight.x * W;
  const fy1 = botRight.y * H;
  rect(fx0, fy0, fx1 - fx0, fy1 - fy0, 38, 42, 52);
  rect(fx0, fy0, (fx1 - fx0) * 0.16, fy1 - fy0, 62, 32, 38); // red end
  rect(fx1 - (fx1 - fx0) * 0.16, fy0, (fx1 - fx0) * 0.16, fy1 - fy0, 32, 44, 68); // blue end
  rect((fx0 + fx1) / 2 - 1, fy0, 2, fy1 - fy0, 70, 76, 90); // center line

  const drawn = [];
  for (const r of ROBOTS) drawn.push({ b: project(pos(r.team, t)), team: r.team, alliance: r.alliance });
  if (t >= UNKNOWN_TRACK.from && t <= UNKNOWN_TRACK.to) {
    drawn.push({ b: project(unknownPos(t)), team: null, alliance: null });
  }
  drawn.sort((a, b) => a.b.y - b.b.y); // painter's algorithm: nearer robots last
  for (const d of drawn) {
    const x = d.b.x * W;
    const y = d.b.y * H;
    const w = d.b.w * W;
    const h = d.b.h * H;
    const col = d.alliance === 'red' ? [196, 54, 62] : d.alliance === 'blue' ? [48, 104, 200] : [120, 124, 134];
    rect(x, y, w, h, col[0], col[1], col[2]);
    rect(x + 2, y + 2, w - 4, h - 4, 24, 26, 32); // chassis inside the bumpers
    if (d.team != null) {
      const s = Math.max(1, Math.round(w / 16));
      const label = String(d.team);
      digits(label, x + (w - label.length * 4 * s) / 2, y + (h - 5 * s) / 2, s, 236, 238, 242);
    }
  }
}

const nFrames = Math.round(DURATION * FPS);
const ff = spawn(
  'ffmpeg',
  ['-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', W + 'x' + H, '-r', String(FPS), '-i', 'pipe:0',
   '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30', '-pix_fmt', 'yuv420p',
   '-movflags', '+faststart', resolve(OUT, 'segment.mp4')],
  { stdio: ['pipe', 'ignore', 'pipe'] }
);
let ffErr = '';
ff.stderr.on('data', (d) => { ffErr += d.toString(); });

const write = (buf) =>
  new Promise((res, rej) => {
    if (ff.stdin.write(buf)) res();
    else ff.stdin.once('drain', res);
    ff.stdin.once('error', rej);
  });

console.log('rendering ' + nFrames + ' frames at ' + W + 'x' + H + '...');
for (let i = 0; i < nFrames; i++) {
  drawFrame(i / FPS);
  await write(frame);
}
ff.stdin.end();
const code = await new Promise((res) => ff.on('close', res));
if (code !== 0) {
  console.error(ffErr.split('\n').slice(-15).join('\n'));
  process.exit(code);
}
console.log('wrote segment.mp4');
