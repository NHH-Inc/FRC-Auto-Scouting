# Open contract questions

**All thirteen questions raised against v1 were resolved in SCHEMA_VERSION 2.** The rulings
are in the changelog at the bottom of `docs/frc-scouting-0-contract.md`, which is normative.
This file is kept as the place to raise the *next* one.

## Status: one open (#14)

| # | Question | Ruling |
|---|---|---|
| 1 | `track_id` on match-level events | Nullable, one event stream, no separate record type |
| 2 | `box_sample_rate` unreachable | Tracks endpoint returns `{ box_sample_rate, tracks }`; collections are objects, never bare arrays |
| 3 | No endpoint reads corrections | Added `GET .../corrections` and `DELETE /api/corrections/:id`; events carry `corrected` + `correction_id` |
| 4 | No progress on the job record | Added `progress` and `stage`; `stage` is a closed enum |
| 5 | No retry, no timestamps | `POST /api/jobs/:job_id/retry` reuses the id, increments `attempt`; added `created_at` / `updated_at` |
| 6 | Unspecified response shapes | All three written out; `tba_available` and `rows_skipped` added |
| 7 | Season config location | `/contracts/seasons/<year>.json`, **per year**, selected by `season` on the job |
| 8 | Unmarked gaps in tracks | Required `gaps` array with a `gap_reason` enum; tracks are not split |
| 9 | Docs contradict Contract B | Contract B authoritative; docs 1 and 3 patched |
| 10 | Track-level correction | `PATCH /api/jobs/:job_id/tracks/:track_id` + `scope` on corrections |
| 11 | Cycle time defined twice | Acquire-to-acquire, per team; now in doc 0's vocabulary |
| 12 | Endgame boundary unowned | `phase` derived from the season config by both components |
| 13 | Media metadata before download | Conditional nullability accepted; `error_code` added as a closed enum |

Two of the provisional stances were wrong in ways that would have caused real damage, and
both are worth remembering:

- **Splitting tracks at gaps** would have undone re-identification, whose entire purpose is
  stitching a robot's fragments into one logical track. The ruling keeps one track with holes
  marked explicitly.
- **A single current-season config** breaks the first time someone loads 2025 footage, and
  they will. Season is per-year and selected by the job.

The threshold heuristic that stood in for #8 (`MAX_INTERPOLATION_GAP_PERIODS` in
`web/src/lib/tracks.ts`) has been deleted in favour of the real `gaps` array.

## Raising the next one

Doc 0: *"Anything that feels like it needs a new shared field is a contract change. Raise it
instead of adding it locally."* Add it here with a provisional stance, keep the stance
isolated to one file, and bump `SCHEMA_VERSION` only once all three agree.


---

## Open

### 14. `shot_made` does not say which goal it went in

The season config prices goals separately (`shot_made_high` / `shot_made_low`), but
`event_type` is a closed set with no goal field, so an event cannot say where the piece went.
Score reconstruction currently reads the *high* value for every made shot, in both
`ingest/stats.py` and `web/src/lib/stats.ts`.

**Agreed design (Robert + Justin): Option A.** Add an optional `goal` field to Contract B —
additive, backward compatible, and doc 0 says additive changes "bump the version and stay
backward compatible". The alternatives were splitting `shot_made` into per-goal event types
(a bigger change for the same information) or collapsing to one value per phase (wrong the
moment a game prices goals differently).

**Not applied, deliberately, on two counts.**

1. Doc 0 requires all three people for a contract change, and whoever owns component 1 has
   not weighed in. Two of three delegating is not three agreeing.
2. It has no effect yet. Every point value in `contracts/seasons/2026.json` is a zero
   placeholder, and the *goal names* themselves are placeholders for a game that is not
   public. Adding a field whose legal values we cannot specify is premature.

**Trigger:** apply it when the 2026 game is public and the real goal names are known — the
same change that replaces the placeholder point values. Doing both at once is one migration
instead of two.
