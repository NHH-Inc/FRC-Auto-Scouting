# /web — component 3 (SCHEMA_VERSION 3)

UI, player, overlay, corrections, Sheets export. TypeScript + React + Vite.

## Running

    npm install
    npm run dev        # http://localhost:5173

Runs against `/fixtures/` with **no backend**, which is the default and what doc 0 asks for.
To point at a real ingest service, copy `.env.example` to `.env` and set
`VITE_API_MODE=http`; Vite proxies `/api` to `localhost:8080`.

    npm run typecheck
    npm run build
    npm run validate:fixtures

## Boundaries this component respects

- **Talks only to component 2, only over HTTP.** No imports from `analysis/` or `ingest/`,
  no shelling out to yt-dlp, no direct TBA or YouTube API calls. Every call lives in
  `src/api/`.
- **snake_case never leaks past `src/contracts/index.ts`.** Wire types mirror
  `/contracts/*.schema.json`; the domain types are camelCase; the parsers are the only
  crossing point.
- **`start_offset` is added in exactly one place** — `toOriginalVideoTime()` in
  `src/lib/format.ts`, used only for YouTube deep links. Doc 0: "nothing else ever should."
- **Aggregates are never stored.** Every stat in `src/lib/stats.ts` is a query over the
  event list.
- **Unknown enum values are dropped and reported**, never coerced. They surface in the
  sidebar under "Contract violations." Doc 0: "Anything unrecognized is a bug, not a
  fallback."

## Layout

    src/contracts/   wire <-> domain types, closed sets, parsers    the only snake_case in web/
    src/api/         ScoutingApi interface, HTTP client, fixture client, assumed shapes
    src/lib/         box interpolation, corrections layer, aggregates, formatting
    src/state/       useJobs (queue + polling), useMatch (events/tracks/accuracy)
    src/player/      <video> + canvas overlay, requestVideoFrameCallback
    src/views/       timeline, team stats, heat map, accuracy
    src/components/  sidebar/queue, event inspector + corrections, export
    src/season.ts    reads contracts/season_2026.json

## Player

A self-hosted `<video>`, not the YouTube iframe. Doc 3 is explicit that `getCurrentTime()`
"is coarse and drifts" and the overlay "will visibly lag and jitter." `requestVideoFrameCallback`
gives the exact `mediaTime` of each presented frame, which is what makes frame-accurate
review possible; there is an rAF fallback for browsers without it (Firefox), and it is
visibly looser.

The local player mounts as soon as yt-dlp has written `local_path`; it does not wait for the
analysis process to finish. It includes frame and one-second stepping, speed, volume/mute,
fullscreen, local seeking through HTTP byte ranges, and a readable codec/load error state.

Boxes are interpolated between track samples — the fixture samples at 5 Hz against 30 fps
video, so five frames in six are interpolated. Interpolation **stops** inside a declared gap
(Contract C's `gaps` array): a skipped shot-change segment is a hole where nothing was
observed, and gliding a robot through footage nobody analyzed would be fabricated data
rendered at the same confidence as real data. v1 guessed at this with a sample-spacing
threshold; v2 gets it as a fact from the pipeline.

Keyboard: `space` play/pause, `←`/`→` frame step, `shift+←`/`→` one second, `b` toggle boxes.

## Corrections

Nothing here mutates a raw event. An edit, delete or create becomes a correction row, and
the view is composed in `src/lib/corrections.ts`. The accuracy panel deliberately scores
**raw** output — scoring the corrected stream would measure the reviewers, not the model.

## Known gaps against the contract

`contracts/OPEN_QUESTIONS.md` has all thirteen. The ones that shape this code most:

All thirteen original questions were resolved in SCHEMA_VERSION 2; the v3 `goal` addition is
also reflected here. The workarounds are gone: `box_sample_rate`
arrives on the tracks response, `corrected`/`correction_id` arrive on each event, retry reuses
the job id, and team attribution is fixed at the track level via
`PATCH /api/jobs/:job_id/tracks/:track_id` — which doc 3 now says to build first, so the
inspector leads with it and treats per-event editing as the exception.
