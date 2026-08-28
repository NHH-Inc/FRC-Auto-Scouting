# /contracts

The only shared surface, per `docs/frc-scouting-0-contract.md`. Owned by everyone.
Nothing here changes without all three people agreeing. Bump `SCHEMA_VERSION` and tell
the other two.

| File | Contract | Status |
|---|---|---|
| `SCHEMA_VERSION` | — | `1` |
| `enums.md` | closed sets, identifiers, units | transcribed from doc 0 |
| `job.schema.json` | A — job record | transcribed from doc 0, one conditional added |
| `events.schema.json` | B — event record | transcribed from doc 0, one open question |
| `tracks.schema.json` | C — track record | transcribed from doc 0 |
| `correction.schema.json` | corrections layer | transcribed from doc 0 |
| `result.schema.json` | D — `result.json` metadata | **key names proposed, not agreed** |
| `season_2026.json` | field dimensions, periods, scoring | **location proposed, not agreed** |
| `OPEN_QUESTIONS.md` | — | thirteen items needing all three people |

Doc 0 names `events.schema.json`, `job.schema.json` and `enums.md`. The other files are
transcriptions of contracts that doc 0 states normatively in prose (Contract C, the
corrections layer, `result.json`, and the season config) but does not give a file for. No
fields were invented; where doc 0 left something genuinely undefined it is in
`OPEN_QUESTIONS.md` rather than settled here.

Validate the fixtures against these schemas with:

    cd web && npm run validate:fixtures

## Merge note — three contract sets became one

Component 2 and component 3 each wrote `/contracts/` independently before comparing, which
is the one directory doc 0 says must not happen twice. They have been merged. **Everything
below is a change from the version committed in `f3713ef`, listed so it can be reviewed
rather than discovered.**

Kept from component 2's version:

- `alliances.red` / `alliances.blue` constrained to exactly 3 teams. Doc 0 says the alliance
  list exists to "narrow bumper OCR candidates to three per side", so three is the point.
  Component 3's version had no such constraint; this is strictly better.
- `match_id` in the job's `required` list.

Changed, with reasons:

- **`events.schema.json`: `event_type` gained its enum.** It was `{"type": "string"}`, which
  accepts any value. Doc 0: "Closed sets... Anything unrecognized is a bug, not a fallback."
- **`events.schema.json`: `track_id` is now nullable.** It was required non-nullable, which
  makes `match_start`, `match_end` and `phase_change` unrepresentable — none of them belong
  to a track. See OPEN_QUESTIONS #1; this is flagged, not settled.
- **`job.schema.json`: `match_id` is now nullable.** It was `{"type": "string"}`. Contract E
  is explicit: "returns the job with `match_id: null` if it cannot" resolve it. The ingest
  service currently substitutes the string `"unknown"`, which is not a valid TBA key and
  collides across every unresolved job.
- **`job.schema.json`: `duration`/`fps`/`width`/`height` are nullable, conditionally
  required.** They cannot be known before the download completes, and they must be present
  after it. See OPEN_QUESTIONS #13.
- **`job.schema.json`: `error` is required when `status` is `failed`.** Doc 2 treats failed
  downloads as routine; a retry path needs a reason to show.
- **`enums.md` gained the units and coordinate systems section**, verbatim from doc 0: time
  base, image space, field space, confidence, booleans, identifier formats, naming. Doc 0
  calls these "the most likely source of silent breakage" and component 2's version omitted
  them entirely.
- **Added** `SCHEMA_VERSION` (doc 0: "an integer in `/contracts/`"), plus the track,
  correction, result and season-config files.
- Schemas moved from draft-07 to 2020-12. `jsonschema` on the Python side and `ajv` on the
  TypeScript side both support it.
