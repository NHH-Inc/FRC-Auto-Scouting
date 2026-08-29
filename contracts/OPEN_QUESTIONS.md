# Open contract questions

**All thirteen questions raised against v1 were resolved in SCHEMA_VERSION 2.** The rulings
are in the changelog at the bottom of `docs/frc-scouting-0-contract.md`, which is normative.
This file is kept as the place to raise the *next* one.

## Status: none open

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

## Resolved after v2

### 14. `shot_made` did not say which goal it went in — RESOLVED in v3

The season config prices goals separately, but `event_type` is a closed set with no goal
field, so an event could not say where the piece went. Score reconstruction read the *high*
value for every made shot.

**Resolved: optional `goal` field on Contract B, SCHEMA_VERSION 3.** Additive, so a v2
producer that omits it stays valid and v3 consumers treat absent as null.

The part worth keeping in mind: `goal` is deliberately **not** a closed set in doc 0. Its
legal values are the `goals` array of the season config, because they change every season —
2026 is `high | low`, 2025 is `l1 | l2 | l3 | l4 | processor | net`. A doc-0 enum would have
to be edited every January, which is exactly the churn closed sets exist to avoid. Validation
happens against the season config instead.

**Agreed by all three: Justin, Robert and Nathaniel (shenj).** Doc 0's requirement for a
contract change is met, so SCHEMA_VERSION 3 is legitimate rather than provisional.

The change is additive, so a producer emitting no `goal` stays valid — which is what kept the
tree working between the version bump and each component catching up.
