# FRC Video Scouting

Watches recorded FRC match video and produces per-robot scouting data.

Three components, one repo, no cross-imports. `docs/frc-scouting-0-contract.md` is the only
shared surface and nothing in `/contracts/` changes without all three people agreeing.

    [3] web  ──HTTP──▶  [2] ingest  ──exec──▶  [1] analysis
                             │                       │
                             ├── yt-dlp              └── events.jsonl, tracks.jsonl
                             ├── TBA API
                             └── Postgres

| Dir | Component | Language | Owns |
|---|---|---|---|
| `analysis/` | 1 | C++ | Detection, tracking, OCR, event extraction |
| `ingest/` | 2 | Python | yt-dlp, TBA/YouTube APIs, job queue, HTTP API, the database |
| `web/` | 3 | TypeScript | UI, player, overlay, corrections, Sheets export |
| `contracts/` | — | — | Shared schemas + per-year season configs. **Owned by everyone.** |
| `fixtures/` | — | — | Golden test data. **Owned by everyone.** |
| `docs/` | — | — | The four context documents |

**New here, or just want to run it?** `docs/RUNNING.md` has every command, Windows-first.

## Start here

1. `docs/frc-scouting-0-contract.md` — read before anything else
2. `contracts/README.md` — the schemas, and what changed when the three contract sets merged
3. `contracts/OPEN_QUESTIONS.md` — all thirteen v1 questions are resolved in
   SCHEMA_VERSION 2; this is where the next one gets raised
4. `fixtures/README.md` — the one worked example every component builds against
5. `docs/media-streaming.md` — ad-free preview behavior and the media/time contract for models

## Running component 3 with no backend

    cd web && npm install && npm run dev

Serves the whole UI against `/fixtures/`, including a generated 152-second test clip. Ports are
doc 0 defaults: web `5173`, ingest `8080`, Postgres `5432`.

## Running the real YouTube-to-local player

Install ffmpeg once (yt-dlp uses it to merge YouTube's separate video and audio streams):

    brew install ffmpeg                 # macOS
    # sudo apt install ffmpeg           # Debian/Ubuntu

From the repository root, start the ingest API:

    python3 -m venv .venv
    .venv/bin/pip install -r ingest/requirements.txt
    .\ingest\.venv\Scripts\python -m uvicorn ingest.main:app --reload --port 8080
    # POSIX: ingest/.venv/bin/python -m uvicorn ingest.main:app --reload --port 8080

In a second terminal, start the web app in HTTP mode:

    cd web
    npm install
    # put VITE_API_MODE=http in web/.env.local, then:
    npm run dev

Open `http://localhost:5173`, paste a YouTube link, and queue it. An ad-free native preview starts
after metadata resolves while yt-dlp stores the local MP4 under `data/segments/`. The player remains
usable while analysis runs or if the analysis binary is not built yet. Timestamped links such as
`&t=2m10s` download only the remaining section and preserve `start_offset`.

The player toolbar can also switch from **Downloaded file** to **Choose matching video…** to review an
MP4/MOV/WebM already on this computer. Choose **Clipped match segment** when that file starts at
segment time zero, or **Full original recording** to apply the job's `start_offset`. The file stays
in the browser; it is not uploaded. Overlay boxes still come from the selected job's
`tracks.jsonl`, so the recording must be the exact source analyzed for that job. Choosing an
unrelated video does not generate new detections.

In HTTP mode, newly queued links open in **yt-dlp stream** mode immediately. The ingest service
resolves separate browser-compatible video and audio files with local `yt-dlp`, proxies their byte
ranges through `/api/stream/<job-id>/video` and `/audio`, and keeps the two native media elements
synchronized. This path uses no YouTube iframe, controls, or ad player. The background download
continues normally; switch to **Downloaded file** after it finishes for an immutable local copy.
See `docs/media-streaming.md` for endpoint behavior, time/box coordinate invariants, and the rules
future model integrations must follow.

Optional authenticated videos can use a browser cookie source:

    $env:YTDLP_COOKIES_FROM_BROWSER = 'chrome'
    .\ingest\.venv\Scripts\python -m uvicorn ingest.main:app --port 8080

Run the focused ingest tests with:

    .\ingest\.venv\Scripts\python -m pytest ingest\tests -q

## Collecting training frames with local vision models

The offline collection workflow extracts hashed frames from a downloaded segment and compares
robot-box proposals from three local Ollama vision models. See `docs/data-collection.md` for setup,
commands, output files, and the required human-review boundary.

Ollama connects through `http://127.0.0.1:11434` as configured in
`configs/data_collection.example.yaml`. Generated frames, manifests, per-model proposals, and
comparison reports are written to the Git-ignored `data/collections/<collection-id>/` directory.
They are review inputs, not accepted training labels or analyzer output.

## Checking a component against the contracts

    cd web && npm run validate:fixtures

## Configuration

Component 2 reads these from the environment. All are optional; the service runs without
them, degrading rather than failing.

| Variable | Effect when unset |
|---|---|
| `TBA_API_KEY` | `alliances` and `tba_score` stay null. Component 1 falls back to raw OCR without elimination, and the accuracy comparison has nothing to score against. |
| `SHEETS_SPREADSHEET_ID` + `GOOGLE_APPLICATION_CREDENTIALS` | `POST /api/export/sheets` returns 503 rather than reporting a write that did not happen. Share the sheet with the service account. |
| `DATABASE_URL` | SQLite at `./frc_scouting.db`. Set to a Postgres URL in production. |
| `FRC_DATA_DIR` | `./data` — segments in `data/segments/`, job output in `data/jobs/`. |
| `ANALYSIS_BINARY` | `./analysis/build/bin/analysis` |
| `FRC_DEFAULT_SEASON` | `2026`, used when a job does not name a season. |

## Checks

    cd web && npm run typecheck && npm run build && npm run validate:fixtures
    ingest\.venv\Scripts\python -m ingest.smoke_test     # 67 Contract E checks
    ingest\.venv\Scripts\python -m pytest ingest/tests -q
