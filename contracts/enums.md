# Enums and shared units

Transcribed from `docs/frc-scouting-0-contract.md`. That document is normative; this
file is the machine-adjacent restatement so all three components can diff against one
thing. **Nothing here changes without all three people agreeing.**

`SCHEMA_VERSION` currently `1` (see `./SCHEMA_VERSION`).

## Closed sets

Adding a value is a contract change. Anything unrecognized is a bug, not a fallback.

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

`source` is how a consumer tells a model-inferred event from a corrected one or an
API-derived one. Every event has it.

Correction actions are their own closed set:

```
correction_action = edit | delete | create
```

## Identifier formats

| Thing | Format | Example |
|-------|--------|---------|
| `match_id` | TBA match key, lowercase | `2026casf_qm42` |
| `video_id` | YouTube ID, 11 chars, case-sensitive | `dQw4w9WgXcQ` |
| `job_id` | UUIDv4 | `f81d4fae-7dec-11d0-a765-00a0c91e6bf6` |
| `team` | integer, no leading zeros, no `frc` prefix | `254` |
| `track_id` | integer, unique within a job only | `7` |

Team numbers are integers everywhere. TBA returns them as `frc254`; the prefix is
stripped at the ingest boundary so nothing downstream ever sees it.

## Units and coordinate systems

**Time.** Float seconds, three decimal places. `t_seconds` is always relative to the
start of the *segment*, not the original video. To get a position in the original
video, add `start_offset` from the job record. Component 3 does that conversion when
linking to YouTube; nothing else ever should.

**Image space.** Normalized floats, `0.0` to `1.0`. Origin at top-left. `x` right,
`y` down. Never pixels.

**Field space.** Feet, float. Origin at the center of the field. `+x` toward the blue
alliance wall, `+y` toward the scoring table side. Nominal field dimensions live in the
season config, not in code.

**Confidence.** Float `0.0` to `1.0`. Never a percentage, never a string.

**Booleans.** Actual booleans in JSON. Not `0`/`1`, not `"true"`.

## Naming

`snake_case` in JSON, SQL, C++ and Python. `camelCase` only inside TypeScript,
converted at the API boundary (component 3 owns that conversion; see
`web/src/contracts/convert.ts`).

## Timestamps

Metadata timestamps: ISO 8601, UTC, `Z` suffix. Timestamps within video: float seconds.
