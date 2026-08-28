// Validates every fixture against /contracts/*.schema.json.
//
// Doc 0: "If your component works against the fixtures, it will work against the others."
// That only holds if the fixtures actually satisfy the contracts, so this checks. Run it
// before trusting anything the UI shows:
//
//     npm run validate:fixtures
//
// Exits nonzero on the first schema that fails, so it can go straight into CI.

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

function check(kind, rows, label) {
  const validate = validators[kind];
  let bad = 0;
  rows.forEach((row, i) => {
    checked++;
    if (!validate(row)) {
      bad++;
      failures++;
      if (bad <= 3) {
        const where = rows.length > 1 ? ` [row ${i + 1}]` : '';
        console.error(`  FAIL ${label}${where}`);
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

const dirs = readdirSync(FIXTURES).filter(
  (d) => statSync(join(FIXTURES, d)).isDirectory() && d !== 'tools'
);
if (dirs.length === 0) {
  console.error('No fixture directories found. Run: node fixtures/tools/generate_fixture.mjs');
  process.exit(1);
}

for (const dir of dirs) {
  const base = join(FIXTURES, dir);
  console.log(`fixtures/${dir}`);

  const files = {
    job: ['job.json', 'job', readJson],
    result: ['result.json', 'result', readJson],
    events: ['events.jsonl', 'event', readJsonl],
    tracks: ['tracks.jsonl', 'track', readJsonl],
    corrections: ['corrections.jsonl', 'correction', readJsonl],
  };

  for (const [name, kind, read] of Object.values(files)) {
    const path = join(base, name);
    if (!existsSync(path)) {
      // corrections.jsonl is component 3's addition, not one of doc 0's five artifacts.
      if (name === 'corrections.jsonl') continue;
      console.error(`  MISS ${name}`);
      failures++;
      continue;
    }
    const parsed = read(path);
    check(kind, Array.isArray(parsed) ? parsed : [parsed], name);
  }

  // Cross-file invariants the schemas cannot express on their own.
  const job = readJson(join(base, 'job.json'));
  const events = readJsonl(join(base, 'events.jsonl'));
  const tracks = readJsonl(join(base, 'tracks.jsonl'));

  const problems = [];

  // Contract B: "in ascending t_seconds order".
  for (let i = 1; i < events.length; i++) {
    if (events[i].t_seconds < events[i - 1].t_seconds) {
      problems.push(`events.jsonl not sorted by t_seconds at row ${i + 1}`);
      break;
    }
  }

  const ids = new Set();
  for (const e of events) {
    if (ids.has(e.event_id)) problems.push(`duplicate event_id ${e.event_id}`);
    ids.add(e.event_id);
    if (e.job_id !== job.job_id) problems.push(`event ${e.event_id} has a foreign job_id`);
    if (e.match_id !== job.match_id) problems.push(`event ${e.event_id} has a foreign match_id`);
    if (e.t_seconds > job.duration) problems.push(`event ${e.event_id} is past the segment end`);
  }

  const trackIds = new Set(tracks.map((t) => t.track_id));
  for (const e of events) {
    if (e.track_id != null && !trackIds.has(e.track_id)) {
      problems.push(`event ${e.event_id} references missing track ${e.track_id}`);
    }
  }

  // Image space is normalised 0..1 (doc 0). A box outside it means a pixel leaked through.
  for (const t of tracks) {
    for (const b of t.boxes) {
      if (b.x < 0 || b.y < 0 || b.x + b.w > 1.0001 || b.y + b.h > 1.0001) {
        problems.push(`track ${t.track_id} has a box outside normalised image space at t=${b.t}`);
        break;
      }
    }
  }

  // A team on a track must be one of the teams TBA says played.
  if (job.alliances) {
    const playing = new Set([...job.alliances.red, ...job.alliances.blue]);
    for (const t of tracks) {
      if (t.team != null && !playing.has(t.team)) {
        problems.push(`track ${t.track_id} claims team ${t.team}, which is not in this match`);
      }
    }
  }

  const unique = [...new Set(problems)];
  for (const p of unique.slice(0, 8)) {
    console.error(`  FAIL ${p}`);
    failures++;
  }
  if (unique.length > 8) console.error(`       …and ${unique.length - 8} more`);
  if (unique.length === 0) console.log('  ok   cross-file invariants');
  console.log('');
}

if (failures > 0) {
  console.error(`${failures} problem(s) across ${checked} records.`);
  process.exit(1);
}
console.log(`All fixtures valid — ${checked} records against ${Object.keys(validators).length} schemas.`);
