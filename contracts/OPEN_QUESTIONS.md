# Open contract questions

Doc 0: *"Anything that feels like it needs a new shared field is a contract change.
Raise it instead of adding it locally."*

These are the gaps component 3 hit while building against the contract. **None of them
have been resolved unilaterally.** Each has a provisional stance so work was not blocked,
each provisional stance is isolated to one file in `web/` so changing it is cheap, and
each needs all three people to agree before `SCHEMA_VERSION` moves.

---

### 1. `track_id` on match-level events

Contract B says `team` and `field_x` / `field_y` are nullable and *"everything else is
required."* But `match_start`, `match_end` and `phase_change` are not attributable to any
track, so there is no `track_id` to put there.

**Provisional:** `events.schema.json` types `track_id` as `["integer", "null"]`, and
component 3 tolerates `null` or an absent key. Component 3 never uses `track_id` for
match-level events.

**Needs deciding:** nullable `track_id`, a sentinel, or a separate match-level record.

---

### 2. Component 3 has no way to get `box_sample_rate`

Contract C: *"State the sample rate in the job result so it knows how much to
interpolate."* `result.json` (Contract D) carries it, but `result.json` is written by
component 1 and read by component 2 — component 3 only speaks HTTP, and **no Contract E
endpoint exposes it.** `GET /api/matches/:match_id/tracks` returns `[track]` and nothing
else.

**Provisional:** component 3 estimates the sample rate from the median spacing of `t`
values in the boxes it receives, and falls back to a season-config default. This works but
it is inference where the contract intended a stated value.

**Needs deciding:** the cleanest fix is for component 2 to include it on the job record, or
for the tracks endpoint to return `{ box_sample_rate, tracks: [...] }`. Either is a
contract change. Related: `result.json`'s JSON *key names* are described in prose in doc 0
but never written out; `result.schema.json` here proposes them and component 1 should
confirm.

---

### 3. No endpoint lists corrections

Doc 0 keeps corrections as their own layer and says reads apply them by default, with
`?raw=true` for uncorrected. Contract E exposes create / patch / delete for corrections but
nothing that **reads** them, so component 3 cannot show a correction history, mark which
events a human touched, or let a user undo a correction — all things doc 3 asks for
("corrections... become labeled training data").

Also unstated: which endpoints honour `?raw=true`. Presumably
`/api/matches/:match_id/events`.

**Provisional:** component 3 fetches raw and corrected events separately and diffs them
locally to reconstruct what changed. Correct, but two requests where one would do, and it
cannot recover `created_at` or who made the correction.

**Needs deciding:** add `GET /api/matches/:match_id/corrections`.

---

### 4. Job record carries no progress

Contract D has component 1 emit `{"progress": 0.42, "stage": "tracking"}` to stdout
*"so component 2 can show a progress bar"* — but component 2 has no UI. Component 3 is what
shows the progress bar, and Contract A's job record has no `progress` or `stage` field, so
polling `GET /api/jobs/:job_id` returns only a coarse status.

**Provisional:** component 3 renders an indeterminate bar for `downloading` / `analyzing`
and reads optional `progress` / `stage` keys if they happen to be present.

**Needs deciding:** add `progress` (float 0..1, nullable) and `stage` (string, nullable) to
Contract A.

---

### 5. Job record has no timestamps and no retry endpoint

Doc 3: *"Failures are routine and need a retry path that does not require re-pasting the
link."* Contract E has `POST /api/jobs`, `DELETE /api/jobs/:job_id`, and no retry. Contract
A also has no `created_at`, so the queue cannot be ordered by age.

**Provisional:** component 3 retries by re-POSTing `/api/jobs` with the `video_id` and
`match_id` it already holds, so the user never re-pastes. This creates a *new* `job_id`,
which orphans the failed job's history.

**Needs deciding:** `POST /api/jobs/:job_id/retry`, plus `created_at` on the job record.

---

### 6. Unspecified response shapes

Contract E names these endpoints but not what they return. Component 3 assumed a shape for
each; all three live in `web/src/api/shapes.ts` with the assumption written at the top.

| Endpoint | Assumed |
|---|---|
| `GET /api/matches/:match_id/accuracy` | `{ match_id, reconstructed: {red,blue}, tba: {red,blue}, delta: {red,blue} }` |
| `GET /api/teams/:team/stats` | `{ team, event_key, matches_played, ...aggregate fields }` |
| `POST /api/export/sheets` | `{ spreadsheet_id, spreadsheet_url, rows_written, mode }` |

The export one matters most: without a URL back, the UI cannot link the user to the sheet
it just wrote.

---

### 7. Where the season config lives

Doc 0: *"Nominal field dimensions live in the season config, not in code."* It does not say
where that config is. Component 1 needs the dimensions for homography and component 3 needs
them for the field heat map, and doc 0 forbids cross-imports between component
directories — which leaves `/contracts/` as the only place both can read it from.

**Provisional:** `contracts/season_2026.json`, holding field dimensions, period lengths and
point values. The scoring values in it are placeholders.

**Needs deciding:** confirm the location, and replace the placeholder point values once the
2026 game is public.

---

## Raised after reading docs 1 and 2

Items 1-7 came from building component 3 against doc 0. These came from comparing doc 0
against what documents 1 and 3 actually tell their owners to build. **Items 9 and 10 will
break the integration if they are not settled before component 1 emits real output.**

---

### 8. A skipped shot-change segment leaves an unmarked hole in a track

Doc 1: broadcast shot changes "should be detected and skipped, not analyzed", and Contract D
has `result.json` report `frames_skipped_shot_change`. So a track's `boxes` array will have
gaps where nothing was observed.

Contract C gives no way to mark one -- `boxes` is a flat array, and a 4-second hole looks
exactly like a low sample rate. Component 3 interpolating across it draws a robot gliding
through footage nobody analyzed, rendered identically to real observation.

**Provisional:** component 3 refuses to interpolate across gaps longer than 3 sample periods
and draws nothing there (`web/src/lib/tracks.ts`, `MAX_INTERPOLATION_GAP_PERIODS`). A
threshold is a guess, not a signal.

**Needs deciding:** either emit a separate track per continuous observation run, or add an
explicit gap list. Splitting tracks is cleaner but changes what `track_id` means.

---

### 9. Documents 1 and 3 describe an event row that Contract B contradicts

Both doc 1 ("Output format") and doc 3 ("Storage") state the event row as:

```
{ match_id, team, t_seconds, phase, event_type, confidence, field_x, field_y }
```

Contract B requires thirteen fields. **Five are missing from that list:**
`schema_version`, `job_id`, `event_id`, `track_id`, `source`.

This is not cosmetic:

- **No `event_id`** and the entire corrections layer cannot exist. Every correction
  references an event by id, and `PATCH`/`DELETE /api/events/:event_id` have nothing to
  address.
- **No `source`** and a model inference, a scoreboard OCR read and a human correction are
  indistinguishable — which destroys both the accuracy comparison and the training-data
  export, since neither can tell model output from ground truth.
- **No `track_id`** and events cannot be tied to the box that produced them, so clicking an
  event cannot highlight a robot.

Doc 0 is normative ("This document is the only shared surface"), so Contract B wins. But
whoever builds component 1 from doc 1 alone will emit the eight-field row and it will look
correct to them.

**Needs deciding:** nothing about the contract — it needs docs 1 and 3 corrected to point at
Contract B instead of restating a stale subset.

---

### 10. Team attribution is a property of a track, but only events can be corrected

Doc 3's core correction is "fix the team attribution". Doc 1 says a team number is stamped
onto a **track** and propagated "across the track's full lifetime, backward and forward".
Contract C puts `team` on the track, for exactly that reason.

But Contract E only offers `PATCH /api/events/:event_id`. When bumper OCR misreads a robot,
every event on that track is wrong — forty-odd rows in a single match. The UI can only fix
them one at a time, and the boxes stay mislabelled no matter how many events are corrected,
because the overlay reads `team` from the track.

This makes the most common correction in the product the most tedious one.

**Needs deciding:** add `PATCH /api/tracks/:track_id` (or a correction with a `track_id`
scope) that re-attributes a track and every event on it as one action.

---

### 11. Cycle time is defined two different ways

Doc 1: "Cycle time: interval between consecutive reload and score events for the same
track" — acquire-to-score.

Doc 3 treats per-robot cycle time as the headline deliverable but never defines it.
Component 3 currently computes acquire-to-acquire (consecutive `reload` events), because a
missed shot should still cost a cycle and because tracks break and re-id mid-match while
teams do not.

The two produce materially different numbers. Whichever is chosen, one metric with one
definition should end up in the shared vocabulary section of doc 0.

Related: doc 1 says "for the same track", but track ids are job-local and a re-identified
robot gets a new one. Cycle time should be computed per **team**, not per track.

---

### 12. Nobody owns the endgame boundary

`phase` is a closed set including `endgame`, and component 1 stamps it on every event.
Component 3 draws phase bands on the timeline from `contracts/season_2026.json`.

Doc 2 says auto is exactly 15s and teleop exactly 135s, so those are deterministic — but
nothing anywhere says when teleop becomes endgame. If component 1 uses a different cutoff
than the season config, the timeline bands and the event phases silently disagree, and the
per-phase point values in the score reconstruction are applied to the wrong events.

**Provisional:** `endgame_seconds: 20`, the final 20s of teleop, in the season config.

**Needs deciding:** confirm the number, and confirm component 1 reads it from the season
config rather than hardcoding one.

---

### 13. Media metadata is unknowable before the download finishes

Contract A's example shows `duration`, `fps`, `width` and `height` all populated, at
`status: "downloaded"`. But a `queued` job cannot know any of them — they come out of the
download. The ingest service models them as nullable columns for exactly that reason.

**Provisional:** `job.schema.json` now types the four as nullable, with a conditional that
requires them non-null once `status` is `downloaded`, `analyzing` or `complete` (and
requires `error` non-null when `status` is `failed`). Component 3 narrows to a `PlayableJob`
before opening the player rather than defaulting a duration.

**Needs deciding:** confirm the conditional. It is a tightening of doc 0, not a loosening —
nothing that was legal before is illegal now except a `complete` job with no media metadata,
which was never usable anyway.
