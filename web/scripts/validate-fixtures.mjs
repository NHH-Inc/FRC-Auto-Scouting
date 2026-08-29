// Validates every fixture against /contracts/*.schema.json at SCHEMA_VERSION 3.
//
// Doc 0: "If your component works against the fixtures, it will work against the others."
// That only holds if the fixtures actually satisfy the contracts, so this checks. It also
// enforces doc 0's requirement that fixture coverage include the awkward cases.
//
//     npm run validate:fixtures

import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv from 'ajv/dist/2020.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');
const CONTRACTS = join(ROOT, 'contracts');
const FIXTURES = join(ROOT, 'fixtures');

const ajv = new Ajv({ allErrors: true, strict: false, validateFormats: false });

const schema = (name) => JSON.parse(readFileSync(join(CONTRACTS, name), 'utf8'));
const readJson = (p) => JSON.parse(readFileSync(p, 'utf8'));
const readJsonl = (p) =>
  readFileSync(p, 'utf8')
    .split('\n')
    .filter((l) => l.trim())
    .map((l, i) => {
      try {
        return JSON.parse(l);
      } catch (e) {
        throw new Error(`${p}:${i + 1} is not valid JSON — ${e.message}`);
      }
    });

const validators = {
  job: ajv.compile(schema('job.schema.json')),
  event: ajv.compile(schema('events.schema.json')),
  track: ajv.compile(schema('tracks.schema.json')),
  correction: ajv.compile(schema('correction.schema.json')),
  result: ajv.compile(schema('result.schema.json')),
};

let failures = 0;
let checked = 0;

function fail(msg) {
  failures++;
  console.error(`  FAIL ${msg}`);
}

function check(kind, rows, label) {
  const validate = validators[kind];
  let bad = 0;
  rows.forEach((row, i) => {
    checked++;
    if (!validate(row)) {
      bad++;
      if (bad <= 3) {
        failures++;
        console.error(`  FAIL ${label}${rows.length > 1 ? ` [row ${i + 1}]` : ''}`);
        for (const err of validate.errors ?? []) {
          console.error(`       ${err.instancePath || '/'} ${err.message}`);
        }
      }
    }
  });
  if (bad > 3) console.error(`       …and ${bad - 3} more in ${label}`);
  if (bad === 0) console.log(`  ok   ${label} (${rows.length})`);
}

const expectedVersion = Number(readFileSync(join(CONTRACTS, 'SCHEMA_VERSION'), 'utf8').trim());
console.log(`SCHEMA_VERSION ${expectedVersion}\n`);

const seasons = readdirSync(join(CONTRACTS, 'seasons')).filter((f) => f.endsWith('.json'));
console.log(`season configs: ${seasons.join(', ')}\n`);

const dirs = readdirSync(FIXTURES).filter(
  (d) => statSync(join(FIXTURES, d)).isDirectory() && d !== 'tools'
);
if (dirs.length === 0) {
  console.error('No fixture directories found. Run: node fixtures/tools/generate_fixture.mjs');
  process.exit(1);
}

// Doc 0: "Fixture coverage must include the awkward cases, not just the happy path."
const coverage = {
  'track with a shot_change gap': false,
  'unidentified track (team: null)': false,
  'match-level event (track_id: null)': false,
  'failed job with an error_code': false,
  'match with alliances: null': false,
  'a shot with a goal': false,
  'a shot whose goal is unknown': false,
};

for (const dir of dirs) {
  const base = join(FIXTURES, dir);
  console.log(`fixtures/${dir}`);

  if (!existsSync(join(base, 'job.json'))) {
    fail(`${dir} has no job.json`);
    continue;
  }
  const job = readJson(join(base, 'job.json'));
  check('job', [job], 'job.json');

  if (job.schema_version !== expectedVersion) {
    fail(`job.schema_version ${job.schema_version} != SCHEMA_VERSION ${expectedVersion}`);
  }
  if (job.status === 'failed' && job.error_code) coverage['failed job with an error_code'] = true;
  if (job.alliances === null) coverage['match with alliances: null'] = true;

  // The season the job names must actually exist.
  if (!existsSync(join(CONTRACTS, 'seasons', `${job.season}.json`))) {
    fail(`job.season ${job.season} has no contracts/seasons/${job.season}.json`);
  }

  // A failed job never produced analysis output; requiring it would be wrong.
  if (job.status === 'failed') {
    console.log('  ok   failed job carries error_code, no analysis output expected');
    console.log('');
    continue;
  }

  for (const [name, kind] of [
    ['result.json', 'result'],
    ['events.jsonl', 'event'],
    ['tracks.jsonl', 'track'],
    ['corrections.jsonl', 'correction'],
  ]) {
    const path = join(base, name);
    if (!existsSync(path)) {
      if (name === 'corrections.jsonl') continue;
      fail(`${name} missing`);
      continue;
    }
    const parsed = name.endsWith('.jsonl') ? readJsonl(path) : [readJson(path)];
    check(kind, parsed, name);
  }

  const events = readJsonl(join(base, 'events.jsonl'));
  const tracks = readJsonl(join(base, 'tracks.jsonl'));
  const result = readJson(join(base, 'result.json'));
  const problems = [];

  // Contract B: "ascending by t_seconds".
  for (let i = 1; i < events.length; i++) {
    if (events[i].t_seconds < events[i - 1].t_seconds) {
      problems.push(`events.jsonl not sorted by t_seconds at row ${i + 1}`);
      break;
    }
  }

  // Legal goal names come from the job's season config, not from a schema -- a schema
  // cannot know which season it is reading.
  const seasonCfg = JSON.parse(
    readFileSync(join(CONTRACTS, 'seasons', `${job.season}.json`), 'utf8')
  );
  const legalGoals = new Set(seasonCfg.goals ?? []);
  const SHOTS = new Set(['shot_attempt', 'shot_made']);

  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const ids = new Set();
  const MATCH_LEVEL = new Set(['match_start', 'match_end', 'phase_change']);
  for (const e of events) {
    if (!UUID.test(e.event_id)) problems.push(`event_id ${e.event_id} is not a UUIDv4`);
    if (ids.has(e.event_id)) problems.push(`duplicate event_id ${e.event_id}`);
    ids.add(e.event_id);
    if (e.job_id !== job.job_id) problems.push(`event ${e.event_id} has a foreign job_id`);
    if (e.match_id !== job.match_id) problems.push(`event ${e.event_id} has a foreign match_id`);
    if (job.duration != null && e.t_seconds > job.duration) {
      problems.push(`event ${e.event_id} is past the segment end`);
    }
    if (e.goal != null) {
      if (!legalGoals.has(e.goal)) {
        problems.push(
          `event ${e.event_id} has goal "${e.goal}", not in season ${job.season}: ` +
            [...legalGoals].join(' | ')
        );
      }
      if (!SHOTS.has(e.event_type)) {
        problems.push(`${e.event_type} ${e.event_id} carries a goal but is not a shot`);
      }
      coverage['a shot with a goal'] = true;
    } else if (SHOTS.has(e.event_type)) {
      coverage['a shot whose goal is unknown'] = true;
    }
    if (MATCH_LEVEL.has(e.event_type)) {
      coverage['match-level event (track_id: null)'] = true;
      if (e.track_id !== null || e.team !== null) {
        problems.push(`${e.event_type} ${e.event_id} must have null team and track_id`);
      }
    }
  }

  const trackIds = new Set(tracks.map((t) => t.track_id));
  for (const e of events) {
    if (e.track_id != null && !trackIds.has(e.track_id)) {
      problems.push(`event ${e.event_id} references missing track ${e.track_id}`);
    }
  }

  for (const t of tracks) {
    if (t.team === null) coverage['unidentified track (team: null)'] = true;
    if (!Array.isArray(t.gaps)) {
      problems.push(`track ${t.track_id} has no gaps array (required, may be empty)`);
      continue;
    }
    for (const g of t.gaps) {
      if (g.reason === 'shot_change') coverage['track with a shot_change gap'] = true;
      if (g.end <= g.start) problems.push(`track ${t.track_id} has a gap ending before it starts`);
      // The whole point of declaring a gap is that nothing was observed inside it.
      const inside = t.boxes.filter((b) => b.t >= g.start && b.t <= g.end);
      if (inside.length > 0) {
        problems.push(
          `track ${t.track_id} has ${inside.length} box(es) inside its ${g.reason} gap`
        );
      }
    }
    for (const b of t.boxes) {
      if (b.x < 0 || b.y < 0 || b.x + b.w > 1.0001 || b.y + b.h > 1.0001) {
        problems.push(`track ${t.track_id} has a box outside normalised image space at t=${b.t}`);
        break;
      }
    }
  }

  // A team on a track must be one of the teams TBA says played -- when TBA said anything.
  if (job.alliances) {
    const playing = new Set([...job.alliances.red, ...job.alliances.blue]);
    for (const t of tracks) {
      if (t.team != null && !playing.has(t.team)) {
        problems.push(`track ${t.track_id} claims team ${t.team}, which did not play this match`);
      }
    }
  }

  if (result.job_id !== job.job_id) problems.push('result.json job_id does not match the job');
  if (result.tracks_emitted !== tracks.length) {
    problems.push(`result.tracks_emitted ${result.tracks_emitted} != ${tracks.length} tracks`);
  }
  if (result.events_emitted !== events.length) {
    problems.push(`result.events_emitted ${result.events_emitted} != ${events.length} events`);
  }

  const unique = [...new Set(problems)];
  for (const p of unique.slice(0, 8)) fail(p);
  if (unique.length > 8) console.error(`       …and ${unique.length - 8} more`);
  if (unique.length === 0) console.log('  ok   cross-file invariants');
  console.log('');
}

console.log('required awkward-case coverage');
for (const [what, covered] of Object.entries(coverage)) {
  if (covered) console.log(`  ok   ${what}`);
  else fail(`no fixture covers: ${what}`);
}

if (failures > 0) {
  console.error(`\n${failures} problem(s) across ${checked} records.`);
  process.exit(1);
}
console.log(`\nAll fixtures valid — ${checked} records against ${Object.keys(validators).length} schemas.`);
