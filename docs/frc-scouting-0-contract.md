# FRC Video Scouting — 0. Shared Contract

Read this before any of the other three documents. Every person and every AI session working on this project reads this file first, regardless of which component they are building.

The other three documents describe *what* each component does. This one defines *how they connect*. If three people build against these definitions independently, the pieces fit together on the first try. If anyone deviates, they do not.

## The rule

**This document is the only shared surface. Nothing in it changes without all three people agreeing.**

Everything else is private to its component. How the C++ backend structures its classes is nobody else's business. What the event JSON looks like is everybody's business.

If you need something added to a contract here, that is a conversation, not a commit. Bump `SCHEMA_VERSION` and tell the other two.

## Components and ownership

| # | Component | Language | Owns | Document |
|---|-----------|----------|------|----------|
| 1 | Analysis backend | C++ | Detection, tracking, OCR, event extraction | `frc-scouting-1-ai.md` |
| 2 | Ingest service | Python | yt-dlp, TBA/YouTube APIs, job queue, HTTP API | `frc-scouting-2-youtube.md` |
| 3 | Web app | TypeScript | UI, player, overlay, corrections, Sheets export | `frc-scouting-3-webapp.md` |

Component 2 is also the orchestrator. It owns the database and the HTTP API. Component 1 is a command-line binary it invokes. Component 3 only ever talks to component 2 over HTTP. Component 1 and component 3 never touch each other.

```
[3] Web app  ──HTTP──▶  [2] Ingest service  ──exec──▶  [1] Analysis binary
                              │                              │
                              ├── yt-dlp                     └── writes events.jsonl
                              ├── TBA API
                              └── Postgres
```

## Repository layout

Monorepo. One repo, three top-level directories, no cross-imports.

```
/analysis/        C++ — component 1
/ingest/          Python — component 2
/web/             TypeScript — component 3
/contracts/       shared schemas, owned by everyone
  events.schema.json
  job.schema.json
  enums.md
/fixtures/        golden test data, owned by everyone
/docs/            these four documents
```

`/contracts/` and `/fixtures/` are the only directories more than one person edits.

## Shared vocabulary

Use these exact terms in code, comments, and column names. Do not invent synonyms.

- **match** — one FRC match. Identified by TBA match key.
- **video** — a YouTube video. Identified by its 11-character ID.
- **segment** — the portion of a video containing one match. May be the whole video.
- **job** — one segment queued for analysis.
- **track** — one robot followed across frames by ByteTrack. Has a `track_id`, arbitrary and job-local.
- **team** — an FRC team number. Integer. Resolved from a track by bumper OCR.
- **event** — a single timestamped thing that happened, attributed to a team.
- **detection** — one box in one frame. Internal to component 1. Never crosses a boundary.

## Identifier formats

| Thing | Format | Example |
|-------|--------|---------|
| `match_id` | TBA match key, lowercase | `2026casf_qm42` |
| `video_id` | YouTube ID, 11 chars, case-sensitive | `dQw4w9WgXcQ` |
| `job_id` | UUIDv4 | `f81d4fae-7dec-11d0-a765-00a0c91e6bf6` |
| `team` | integer, no leading zeros, no "frc" prefix | `254` |
| `track_id` | integer, unique within a job only | `7` |

Team numbers are integers everywhere. TBA returns them as `frc254`; strip the prefix at the ingest boundary so nothing downstream ever sees it.

## Units and coordinate systems

Getting these wrong is the most likely source of silent breakage, so they are fixed here.

**Time.** Float seconds, three decimal places. `t_seconds` is always relative to the start of the *segment*, not the original video. To get a position in the original video, add `start_offset` from the job record. Component 3 does that conversion when linking to YouTube; nothing else ever should.

**Image space.** Normalized floats, `0.0` to `1.0`. Origin at top-left. `x` right, `y` down. Never pixels, so overlays work at any player size and boxes survive a resolution change.

**Field space.** Feet, float. Origin at the center of the field. `+x` toward the blue alliance wall, `+y` toward the scoring table side. Nominal field dimensions live in the season config, not in code.

**Confidence.** Float `0.0` to `1.0`. Never a percentage, never a string.

**Booleans.** Actual booleans in JSON. Not `0`/`1`, not `"true"`.

## Enums

Closed sets. Adding a value is a contract change. Anything unrecognized is a bug, not a fallback.

```
phase        = auto | teleop | endgame | unknown
alliance     = red | blue
job_status   = queued | downloading | downloaded | analyzing | complete | failed
event_type   = match_start | match_end | phase_change
             | shot_attempt | shot_made
             | reload
             | defense_start | defense_end
             | immobile_start | immobile_end
             | foul
source       = model | scoreboard_ocr | tba | manual
```

`source` is how a consumer tells a model-inferred event from a corrected one or an API-derived one. Every event has it.

## Contract A — Job record

Produced by component 2, consumed by components 1 and 3.

```json
{
  "schema_version": 1,
  "job_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
  "match_id": "2026casf_qm42",
  "video_id": "dQw4w9WgXcQ",
  "local_path": "/data/segments/dQw4w9WgXcQ_00120_00272.mp4",
  "start_offset": 120.0,
  "duration": 152.0,
  "fps": 30.0,
  "width": 1920,
  "height": 1080,
  "status": "downloaded",
  "alliances": {
    "red":  [254, 1678, 971],
    "blue": [118, 148, 2056]
  },
  "tba_score": { "red": 91, "blue": 84 }
}
```

`alliances` comes from TBA and is what component 1 uses to narrow bumper OCR candidates to three per side. It is required before analysis starts. If TBA has no data for the match, the job is still valid but `alliances` is `null` and component 1 falls back to raw OCR without elimination.

## Contract B — Event record

Produced by component 1, stored and served by component 2, rendered by component 3.

```json
{
  "schema_version": 1,
  "job_id": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
  "match_id": "2026casf_qm42",
  "event_id": "f81d4fae-0007",
  "team": 254,
  "track_id": 7,
  "t_seconds": 42.300,
  "phase": "teleop",
  "event_type": "shot_made",
  "confidence": 0.81,
  "field_x": -12.4,
  "field_y": 3.1,
  "source": "model"
}
```

`team` may be `null` if the track was never identified. `field_x` and `field_y` may be `null` if homography failed for that frame range. Consumers must handle both. Everything else is required.

Component 1 writes these as JSON Lines to `events.jsonl`, one object per line, in ascending `t_seconds` order.

## Contract C — Track record

Produced by component 1 alongside events. This is what draws the boxes.

```json
{
  "schema_version": 1,
  "track_id": 7,
  "team": 254,
  "alliance": "red",
  "boxes": [
    { "t": 42.300, "x": 0.412, "y": 0.556, "w": 0.061, "h": 0.078 }
  ]
}
```

Written to `tracks.jsonl`, one object per track. `x` and `y` are the top-left corner in normalized image space, matching the convention above.

Box sampling rate does not need to match video frame rate. Component 3 interpolates between samples. State the sample rate in the job result so it knows how much to interpolate.

## Contract D — Analysis binary invocation

Component 2 calls component 1 as a subprocess. This is the entire interface between them.

```
analysis --job <path/to/job.json> --out <output/dir>
```

On success: exit 0, and `<out>/events.jsonl`, `<out>/tracks.jsonl`, `<out>/result.json` exist.

`result.json` carries per-run metadata: box sample rate, whether homography succeeded, reconstructed score, frames analyzed, frames skipped for shot changes, and model version.

On failure: nonzero exit, human-readable reason on stderr. Progress goes to stdout as one JSON object per line so component 2 can show a progress bar:

```json
{"progress": 0.42, "stage": "tracking"}
```

Component 1 does not write to the database, does not make network calls, and does not know that YouTube exists. It reads a file and writes files.

## Contract E — HTTP API

Component 2 serves, component 3 consumes. JSON in, JSON out. Errors use standard status codes with `{"error": "message"}`.

```
POST   /api/jobs                  { "url": "...", "match_id": "..." }  → job
GET    /api/jobs                  → [job]
GET    /api/jobs/:job_id          → job (poll for status)
DELETE /api/jobs/:job_id

GET    /api/matches/:match_id/events?min_confidence=0.5  → [event]
GET    /api/matches/:match_id/tracks                     → [track]
GET    /api/matches/:match_id/accuracy                   → reconstructed vs tba score

POST   /api/events                → create a manual event  (source: "manual")
PATCH  /api/events/:event_id      → correct one
DELETE /api/events/:event_id

GET    /api/teams/:team/stats?event_key=...  → aggregates
POST   /api/export/sheets         { "match_ids": [...], "mode": "raw"|"aggregate" }

GET    /api/video/:job_id         → serves the local segment file for the player
```

`match_id` is optional on job creation. If omitted, component 2 attempts to resolve it from the video metadata and returns the job with `match_id: null` if it cannot.

## Corrections

Corrections never overwrite model output. A correction is a new row referencing the original.

```json
{
  "correction_id": "...",
  "event_id": "f81d4fae-0007",
  "action": "edit" | "delete" | "create",
  "fields": { "team": 1678 },
  "created_at": "2026-08-28T14:22:00Z"
}
```

Reads apply corrections on top of raw events by default. A `?raw=true` parameter returns uncorrected output, which is what the accuracy comparison and the training-data export use. Keeping both is the whole point: overwriting destroys the ability to measure whether the model is improving.

## Database

Component 2 owns the schema and is the only thing that writes to it. Postgres in production, SQLite acceptable locally.

Tables: `jobs`, `events`, `tracks`, `corrections`, `matches`.

`events` stores raw model output only. Aggregates are never stored, only queried. If a stat is needed often enough to hurt, add a materialized view, not a column.

## Versioning

`SCHEMA_VERSION` is an integer in `/contracts/`. Every record carries it.

Additive changes (a new optional field, a new enum value) bump the version and stay backward compatible. Consumers ignore fields they do not recognize.

Breaking changes (renaming, removing, changing a type or a unit) require all three components to update together. Avoid them.

## Golden fixtures

`/fixtures/` contains one fully worked example: a short match segment, its job record, a hand-verified `events.jsonl`, a `tracks.jsonl`, and a snapshot of the TBA response.

This exists so all three people can work alone. Component 3 builds the whole UI against fixture data with no backend running. Component 2 tests the pipeline with a stub binary that copies the fixture output. Component 1 validates against hand-verified ground truth.

**If your component works against the fixtures, it will work against the others.** Adding a feature means adding a fixture case for it first.

## Working in parallel

- Build against the contracts and the fixtures, not against the other person's actual code.
- Do not wait for someone else's component. If it does not exist, stub it from a fixture.
- Do not reach across a boundary because it is faster. Component 3 wanting to shell out to yt-dlp, or component 1 wanting to hit the TBA API, is how this ends up unmergeable.
- Anything that feels like it needs a new shared field is a contract change. Raise it instead of adding it locally.
- If an AI session suggests changing a schema, a unit, or a coordinate convention to make its part easier, say no. The convention is not there because it is optimal, it is there because it is agreed.

## Defaults

These are arbitrary and can be changed once, together, at the start. After that, leave them.

- Ports: ingest API `8080`, web dev server `5173`, Postgres `5432`
- Segment storage: `/data/segments/`, job output: `/data/jobs/<job_id>/`
- Naming: `snake_case` in JSON, SQL, C++, and Python. `camelCase` only inside TypeScript, converted at the API boundary.
- Timestamps in metadata: ISO 8601, UTC, `Z` suffix. Timestamps within video: float seconds.

## Working preferences

Direct answers, no hedging. Plain explanations over dense technical prose. Do not restate this document back; assume it is understood and answer the actual question.
