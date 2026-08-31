# /fixtures — SCHEMA_VERSION 3

Doc 0: *"`/fixtures/` contains one fully worked example... This exists so all three people can
work alone."*

## `2026casf_qm42/`

A synthetic 2:32 match. Not real footage — real footage cannot be committed — but internally
consistent in a way that makes it useful as ground truth:

| File | Contract | What it is |
|---|---|---|
| `job.json` | A | The job record. `start_offset: 120`, so segment time ≠ original video time and the YouTube deep-link conversion is actually exercised. |
| `events.jsonl` | B | 237 events, ascending `t_seconds`. |
| `tracks.jsonl` | C | 7 tracks sampled at **5 Hz** against 30 fps video, so consumers must interpolate — with a required `gaps` array and `team_confidence`. |
| `result.json` | D | Run metadata, including `box_sample_rate`. |
| `tba_match.json` | — | TBA response snapshot, with `frc254`-style keys intact: this is the boundary where component 2 strips the prefix. |
| `corrections.jsonl` | F | Three corrections, including a **track-scoped** one — doc 3's primary correction path. |
| `segment.mp4` | — | 640×360, 30 fps, exactly 152.000 s, ~820 KB. |

### Why the video is generated, not stubbed

`segment.mp4` renders the *same* motion model that produced `tracks.jsonl`, so a box that
does not sit on the robot beneath it is a real bug in the consumer, not fixture drift. Each
robot has its team number drawn on it, so the overlay's label can be checked by eye.

### The awkward cases doc 0 requires

Doc 0: "Fixture coverage must include the awkward cases, not just the happy path." All five
are covered and `npm run validate:fixtures` fails if any goes missing:

| Case | Where |
|---|---|
| track with a `shot_change` gap | every robot track, 61.2 – 65.4 s |
| unidentified track (`team: null`) | track 14, 88 – 96 s |
| match-level event (`track_id: null`) | `match_start`, two `phase_change`, `match_end` |
| failed job with an `error_code` | `fixtures/failed_download/` (`rate_limited`, attempt 2) |
| match with `alliances: null` | `fixtures/2026casf_qm43_no_tba/` |

The shot-change gap is real, not asserted: the rendered video cuts away to a blank frame for
those 4.2 seconds, no boxes are sampled inside it, and the two straddling samples sit 4.6 s
apart — exactly the hole that is indistinguishable from a low sample rate unless it is
declared.

### What else it exercises

- **971 goes immobile** 72.4 s → 95.1 s (`immobile_start`/`immobile_end`), producing one huge
  cycle-time outlier — which is why cycle time is reported as a median. It also carries a
  second `occlusion` gap and the lowest `team_confidence` (0.58), so it sorts to the top of
  the track-correction list.
- **2056 plays defense** 40.2 s → 70.6 s and stops scoring.
- **Homography fails** 100 s → 110 s: `field_x`/`field_y` are `null` there. Consumers must
  handle it; the heat map reports the count rather than dropping them silently.
- **Track 14 is unidentified** (`team: null`, `alliance: null`), visible 88 s → 96 s, with one
  low-confidence event attributed to no team.
- **Match-level events** (`match_start`, `match_end`, `phase_change`) carry `track_id: null` —
  see `contracts/OPEN_QUESTIONS.md` #1.
- **Confidence spreads across 0.05–0.99**, so a threshold filter has something to bite on.
- **`reconstructed_score` is null.** Every point value in the 2026 season config is still a
  zero placeholder, so a reconstruction would be zero by construction. Doc 0: "Do not invent
  values to make a test pass." The accuracy panel says so instead of showing a confident
  delta against `tba_score` (91/84).

### Regenerating

    node fixtures/tools/generate_fixture.mjs            # data + video (needs ffmpeg)
    node fixtures/tools/generate_fixture.mjs --no-video # data only

Deterministic: same seed in, byte-identical JSON out. Adding a feature means adding a
fixture case for it first, per doc 0.

### Validating

    cd web && npm run validate:fixtures

Checks every record against `/contracts/*.schema.json`, plus cross-file invariants the
schemas cannot express: ascending `t_seconds`, unique `event_id`, no event referencing a
missing track, boxes inside normalised image space, and no track claiming a team that did
not play the match.
