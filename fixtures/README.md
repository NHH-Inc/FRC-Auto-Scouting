# /fixtures

Doc 0: *"`/fixtures/` contains one fully worked example... This exists so all three people can
work alone."*

## `2026casf_qm42/`

A synthetic 2:32 match. Not real footage — real footage cannot be committed — but internally
consistent in a way that makes it useful as ground truth:

| File | Contract | What it is |
|---|---|---|
| `job.json` | A | The job record. `start_offset: 120`, so segment time ≠ original video time and the YouTube deep-link conversion is actually exercised. |
| `events.jsonl` | B | 237 events, ascending `t_seconds`. |
| `tracks.jsonl` | C | 7 tracks sampled at **5 Hz** against 30 fps video, so consumers must interpolate. |
| `result.json` | D | Run metadata, including `box_sample_rate`. |
| `tba_match.json` | — | TBA response snapshot, with `frc254`-style keys intact: this is the boundary where component 2 strips the prefix. |
| `corrections.jsonl` | — | Three corrections (edit, delete, create). **Not one of doc 0's five artifacts** — added because component 3 cannot demonstrate the corrections view without one. |
| `segment.mp4` | — | 640×360, 30 fps, exactly 152.000 s, ~820 KB. |

### Why the video is generated, not stubbed

`segment.mp4` renders the *same* motion model that produced `tracks.jsonl`, so a box that
does not sit on the robot beneath it is a real bug in the consumer, not fixture drift. Each
robot has its team number drawn on it, so the overlay's label can be checked by eye.

### What it deliberately exercises

Beyond the happy path, so consumers cannot pass by ignoring the hard cases:

- **971 goes immobile** 72.4 s → 95.1 s (`immobile_start`/`immobile_end`), producing one huge
  cycle-time outlier — which is why cycle time is reported as a median.
- **2056 plays defense** 40.2 s → 70.6 s and stops scoring.
- **Homography fails** 100 s → 110 s: `field_x`/`field_y` are `null` there. Consumers must
  handle it; the heat map reports the count rather than dropping them silently.
- **Track 14 is unidentified** (`team: null`, `alliance: null`), visible 88 s → 96 s, with one
  low-confidence event attributed to no team.
- **Match-level events** (`match_start`, `match_end`, `phase_change`) carry `track_id: null` —
  see `contracts/OPEN_QUESTIONS.md` #1.
- **Confidence spreads across 0.05–0.99**, so a threshold filter has something to bite on.
- The **reconstructed score deliberately disagrees with TBA** (83/64 vs 90/60). That gap is
  the accuracy indicator; a fixture where they matched would prove nothing.

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
