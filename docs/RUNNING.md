# Running it

Every command here is **PowerShell on Windows**, because that is what all three of us are on.
POSIX equivalents are noted where they differ.

Two PowerShell gotchas that will bite you first:

- A relative executable needs `.\` — `ingest\.venv\Scripts\python` alone gives
  *"not recognized as the name of a cmdlet"*. Write `.\ingest\.venv\Scripts\python`.
- Environment variables are `$env:NAME = 'value'`, not `NAME=value`. There is no inline
  `VAR=x command` form.

## Which mode do you want?

| I want to… | Go to |
|---|---|
| Look at the UI, click around, try corrections | **A** — no backend needed |
| Paste a YouTube link and watch it download and play | **B** |
| Generate training frames with the local vision models | **C** |
| Check I have not broken anything | **Verifying** |

---

## One-time setup

Run these once per machine, from the repo root.

**Web app** (needs Node 20+):

```bash
cd web
npm install
```

**Ingest service** (needs Python 3.12+ and ffmpeg on PATH):

```bash
python -m venv ingest\.venv
.\ingest\.venv\Scripts\python -m pip install -r ingest\requirements.txt
```

**Config**, if you are going past mode A:

```bash
copy ingest\.env.example ingest\.env
```

Then fill it in. Nothing in it is required — every value degrades rather than breaking — but
without `TBA_API_KEY` you get no alliance data and no accuracy comparison. `.env` is gitignored;
keep it that way.

---

## A — the web app on fixtures, no backend

The fastest way to see the whole UI. Doc 0 asks for this explicitly: *"Component 3 builds the
whole UI against fixture data with no backend running."*

```bash
cd web
npm run dev
```

Open <http://localhost:5173>. You get the golden fixture match: a real 152-second video, seven
tracks with boxes drawn over it, 224 events, working corrections, timeline, stats, heat map and
export panel. Three jobs appear in the queue, including a failed one so you can try the retry
path.

Nothing is mocked in the fake sense — it serves the real fixture data through the same
`ScoutingApi` interface the HTTP client implements, so what renders here renders against the
real backend too.

Corrections you make are kept in browser storage. To reset, clear site data for localhost:5173.

---

## B — the full stack

Two terminals.

**Terminal 1, the ingest service:**

```bash
.\ingest\.venv\Scripts\python -m uvicorn ingest.main:app --reload --port 8080
```

Check it came up: <http://localhost:8080/api/health> should return
`{"status":"ok","schema_version":3,...}`. Interactive API docs are at
<http://localhost:8080/docs>.

**Terminal 2, the web app pointed at it.** Create `web\.env.local` with:

```bash
VITE_API_MODE=http
```

then:

```bash
cd web
npm run dev
```

A file is better than `$env:VITE_API_MODE` because it survives closing the terminal, and Vite
only reads env vars at startup. `.env.local` is gitignored.

Now paste a YouTube link into the sidebar. The job walks
`queued → downloading → downloaded → analyzing → complete`, and the player opens as soon as the
local download finishes — you do not have to wait for analysis.

**Expect analysis to fail** for now, with `error_code: analysis_failed`. Component 1 has a
contract-correct binary but no detection pipeline, so there is nothing to find yet. The download
and the player both work; the boxes are what is missing.

If a video needs sign-in, pass cookies:

```bash
$env:YTDLP_COOKIES_FROM_BROWSER = 'chrome'
.\ingest\.venv\Scripts\python -m uvicorn ingest.main:app --port 8080
```

---

## C — collecting training frames

Needs [Ollama](https://ollama.com) and about 13 GB of disk for the models.

```bash
winget install Ollama.Ollama
ollama pull qwen3-vl:4b
ollama pull qwen2.5vl:7b
ollama pull gemma3:4b
```

Ollama serves on `http://127.0.0.1:11434`, which is what
`configs/data_collection.example.yaml` expects. Confirm it is up with `ollama list`.

**Extract frames from a downloaded segment:**

```bash
.\ingest\.venv\Scripts\python -m ingest.collection.cli extract `
  --segment data\segments\<file>.mp4 `
  --match-id 2026casf_qm42 `
  --video-id dQw4w9WgXcQ `
  --start-offset 120 `
  --config configs\data_collection.example.yaml
```

**Then run the three models over them:**

```bash
.\ingest\.venv\Scripts\python -m ingest.collection.cli annotate `
  --collection <collection-id> `
  --config configs\data_collection.example.yaml
```

Output lands in `data\collections\<collection-id>\` — frames, a manifest, per-model proposals,
and the IoU comparison report. `docs/data-collection.md` has the detail.

**These are review inputs, not training labels.** The whole point of keeping per-model raw
output is that you can see where the models disagreed; feeding unreviewed consensus straight
into training teaches the next model to reproduce this one's mistakes.

### On AMD hardware

Ollama supports RDNA3 on Windows, so an RX 7800 XT runs these GPU-accelerated. **PyTorch does
not** — the ROCm wheels are Linux-only — so training happens on the NVIDIA machine. See
`docs/DECISIONS.md` H1–H3.

---

## Verifying

Run all of it before pushing. CI runs the same four things.

```bash
cd web
npm run typecheck
npm run build
npm run validate:fixtures
```

```bash
.\ingest\.venv\Scripts\python -m pytest ingest\tests -q
.\ingest\.venv\Scripts\python -m ingest.smoke_test
```

What each one is actually checking:

| Command | Checks |
|---|---|
| `validate:fixtures` | Every fixture record against `contracts/*.schema.json`, plus cross-file invariants and the five required awkward cases |
| `smoke_test` | 67 checks driving every Contract E endpoint against the golden fixtures — no network, no yt-dlp, no analysis binary |
| `pytest` | The downloader, collection and API unit tests |

**Component 1** is built by CI rather than locally, because not everyone has a C++ toolchain. To
build it yourself you need CMake and a compiler:

```bash
cmake -S analysis -B analysis\build
cmake --build analysis\build --config Release
```

**Regenerating fixtures** (deterministic, so a clean regeneration is a no-op — CI fails if it
is not):

```bash
node fixtures\tools\generate_fixture.mjs            # includes the video, needs ffmpeg
node fixtures\tools\generate_fixture.mjs --no-video # data only, much faster
```

---

## When something is wrong

**`... is not recognized as the name of a cmdlet`** — you left off the `.\` on a relative path.

**Port 5173 or 8080 already in use** — something is still running from last time:

```bash
Get-NetTCPConnection -LocalPort 5173 -State Listen | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }
```

**The web app shows jobs but no events, and the browser console mentions a module that "does not
provide an export"** — Vite is holding a stale module graph, usually after a `git pull` or branch
switch changed files under it. Restart the dev server; a page refresh is not enough.

**Export returns 503** — that is correct when `SHEETS_SPREADSHEET_ID` and
`GOOGLE_APPLICATION_CREDENTIALS` are not both set. It refuses rather than reporting a write that
never happened. See `docs/DECISIONS.md` D11.

**`alliances` and `tba_score` come back null** — no `TBA_API_KEY`, or TBA genuinely has no data
for that match. Both are legal; component 1 falls back to raw OCR without elimination.

**A job fails immediately** — read `error_code` on the job record, not just the message. It is a
closed enum, and it tells you whether retrying is worth it: `rate_limited` yes,
`video_unavailable` no.
