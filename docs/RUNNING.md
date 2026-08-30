# Running it

PowerShell on Windows, because that is what all three of us use.

**Every command block below starts with the folder you must be in.** Getting this wrong is the
most common mistake — running the ingest setup from inside `web\` creates a junk venv at
`web\ingest\.venv` and fails with *"Could not open requirements file"*.

Two PowerShell rules that catch people out:

- A relative program needs `.\` in front. `ingest\.venv\Scripts\python` alone gives
  *"not recognized as the name of a cmdlet"*. Write `.\ingest\.venv\Scripts\python`.
- Environment variables are `$env:NAME = 'value'`. There is no `NAME=value command` form.

Throughout, **REPO** means `C:\Coding Stuff\Robotics\FRC-Auto-Scouting` — the folder containing
`analysis\`, `ingest\`, `web\`.

---

## The short version

There is one script. It works from any folder, because it resolves paths relative to itself
rather than to your shell.

```bash
# in: REPO
.\run.ps1 setup     # first time only, safe to re-run
.\run.ps1 doctor    # what is installed, what is missing, what is misconfigured
.\run.ps1 web       # the UI on fixture data, no backend
.\run.ps1 full      # ingest service + UI, wired together
.\run.ps1 serve     # build the UI and serve everything on one port
.\run.ps1 check     # every test CI runs
```

`setup` creates the venv, installs both dependency sets, copies `.env.example`, and deletes the
stray `web\ingest\` folder if a previous attempt made one. `full` writes `web\.env.local` for
you — that file is not in the repo, which is why you did not have it.

The rest of this document is what those commands do, for when something goes wrong.

---

## What exists, and what does not

Be clear on this before you go looking for a command that is not there.

| Step | Status | How to run it |
|---|---|---|
| 1. Pull video off YouTube | **works** | Part 3 |
| 2. Extract frames from a segment | **works** | Part 4 |
| 3. Label frames with the 3 local models | **works** | Part 4 |
| 4. Human review of those labels | **not built** | Roboflow, decided but not set up |
| 5. Train a detector | **not built** | no training code exists yet |
| 6. Analyse a match (the C++ backend) | **pipeline proof only** | opens the real MP4, counts frames, and emits one diagnostic box; it does not detect robots yet |
| 7. Review results in the web app | **works** | Part 2 |

So: **there is no "run the training" command**, because nobody has written a trainer. Steps 1–3
produce reviewable proposals; steps 4 and 5 are the gap. Step 6 is the critical path — until the
analysis backend looks at a video, the web app only has fixture data to show.

---

## Part 1 — one-time setup

Do this once per machine. Three separate steps, each in a **different folder**.

### 1a. Web app — needs Node 20+

```bash
# in: REPO\web
cd "C:\Coding Stuff\Robotics\FRC-Auto-Scouting\web"
npm install
```

### 1b. Ingest service — needs Python 3.12+ and ffmpeg on PATH

```bash
# in: REPO   <- the ROOT, not web\
cd "C:\Coding Stuff\Robotics\FRC-Auto-Scouting"
python -m venv ingest\.venv
.\ingest\.venv\Scripts\python -m pip install -r ingest\requirements.txt
```

If you see `Could not open requirements file`, you are in the wrong folder. `cd` to REPO and
retry. If you already made `web\ingest\`, delete it — it is junk:

```bash
# in: REPO
Remove-Item -Recurse -Force web\ingest
```

### 1c. Config

```bash
# in: REPO
copy ingest\.env.example ingest\.env
```

Then open `ingest\.env` and fill in what you have. Nothing is required — every setting degrades
rather than breaking — but without `TBA_API_KEY` you get no alliance data and no accuracy check.
The file is gitignored. Keep it that way, and never paste a key into chat.

---

## Part 2 — the web app on its own

**No backend, no config, no Python.** This is the fastest way to see the whole UI and the right
starting point if you just want to look at it.

```bash
# in: REPO\web
npm run dev
```

Open <http://localhost:5173>.

You get the golden fixture match: a real 152-second video with boxes drawn over it, 224 events,
working corrections, timeline, team stats, heat map, export panel. Three jobs in the queue,
including a deliberately failed one so the retry path is reachable.

Nothing is faked — it serves the real fixture files through the same interface the HTTP client
uses, so anything that renders here renders against the real backend.

To reset corrections you have made: clear site data for `localhost:5173` in your browser.

---

## Part 3 — pulling video off YouTube

This needs the ingest service running. **Two terminals.**

### Terminal 1 — the service

```bash
# in: REPO
cd "C:\Coding Stuff\Robotics\FRC-Auto-Scouting"
.\ingest\.venv\Scripts\python -m uvicorn ingest.main:app --reload --port 8080
```

Check it is alive: <http://localhost:8080/api/health> should say
`{"status":"ok","schema_version":3,...}`. Browsable API docs: <http://localhost:8080/docs>.

### Terminal 2 — the web app, pointed at it

First create the file `web\.env.local` containing one line:

```bash
VITE_API_MODE=http
```

A file, not `$env:`, because Vite only reads env vars at startup and you would lose it every time
you close the terminal. Then:

```bash
# in: REPO\web
npm run dev
```

Now paste a YouTube link into the sidebar. The job walks
`queued → downloading → downloaded → analyzing → complete`, and **the player opens as soon as the
download finishes** — you do not wait for analysis.

**Analysis now proves the full media path**: it opens the downloaded MP4 with OpenCV, counts real
frames, and emits one clearly diagnostic hand-placed box. That confirms download → binary → API →
overlay. It is **not robot detection** and must not be used as scouting data until the detector lands.

Videos that need a login:

```bash
# in: REPO
$env:YTDLP_COOKIES_FROM_BROWSER = 'chrome'
.\ingest\.venv\Scripts\python -m uvicorn ingest.main:app --port 8080
```

Downloaded segments land in `data\segments\`. Note the filename — Part 4 needs it.

---

## Part 4 — labelling frames with the local models

### 4a. Install Ollama and the models (~13 GB)

```bash
# anywhere
winget install Ollama.Ollama
ollama pull qwen3-vl:4b
ollama pull qwen2.5vl:7b
ollama pull gemma3:4b
ollama list
```

Ollama serves on `http://127.0.0.1:11434`, which is what the config expects.

**On AMD:** Ollama supports RDNA3 on Windows, so an RX 7800 XT runs these on the GPU. PyTorch
does *not* support AMD on Windows, which is why training happens on the NVIDIA machine.

### 4b. Extract frames from a segment

Use a file from `data\segments\` that Part 3 downloaded.

```bash
# in: REPO
.\ingest\.venv\Scripts\python -m ingest.collection.cli extract `
  --segment data\segments\<the-file>.mp4 `
  --match-id 2026casf_qm42 `
  --video-id dQw4w9WgXcQ `
  --start-offset 120 `
  --config configs\data_collection.example.yaml
```

The backtick `` ` `` is PowerShell's line continuation. Put it all on one line if you prefer.

It prints a **collection id**. Copy it.

### 4c. Run the three models over those frames

```bash
# in: REPO
.\ingest\.venv\Scripts\python -m ingest.collection.cli annotate `
  --collection <the-collection-id> `
  --config configs\data_collection.example.yaml
```

Models load one at a time so they fit in memory. Output goes to
`data\collections\<collection-id>\`: the frames, a manifest, each model's raw proposals kept
separately, and the IoU comparison report.

**These are proposals, not labels.** Keeping each model's raw output is what lets you see where
they disagreed. Feeding unreviewed consensus straight into training teaches the next model to
copy this one's mistakes — that is why step 4 in the table above exists.

---

## Part 5 — training

**There is no training code in this repo yet.** Nothing to run.

What is decided and waiting for someone to build it:

- Robert's RTX 3060 **12 GB** does the training. That is enough to fine-tune a detector at 640px
  with a normal batch size — no gradient accumulation tricks needed.
- Detector is RF-DETR (Apache 2.0). Not Ultralytics YOLO, which is AGPL-3.0 and needs a paid
  licence for closed source.
- The dataset lives on Roboflow, which is also the review UI step 4 needs.
- The team-ID model is a **classifier** over robot crops, trained separately from the detector.
  The detector learns from (image, box); the classifier learns from (crop, team).

The correction UI in the web app is already producing human-verified `(track → team)` pairs, so
the classifier has a real label source growing on its own. The detector does not — that is what
steps 3 and 4 are for.

---

## Verifying nothing is broken

Run before pushing. `run.ps1 check` runs the same web, ingest, fixture, and C++ checks as CI.

```bash
# in: REPO\web
npm run typecheck
npm run build
npm run validate:fixtures
```

```bash
# in: REPO
.\ingest\.venv\Scripts\python -m pytest ingest\tests -q
.\ingest\.venv\Scripts\python -m ingest.smoke_test
```

| Command | What it actually checks |
|---|---|
| `validate:fixtures` | Every fixture record against `contracts\*.schema.json`, cross-file invariants, and the five required awkward cases |
| `smoke_test` | 71 checks driving every Contract E endpoint against the fixtures — no network, no yt-dlp, no analysis binary |
| `pytest` | Downloader, collection and API unit tests |
| `analysis` | Opens the fixture MP4 with OpenCV, counts its decodable frames, emits the diagnostic track, and checks Contract D output |

**The C++ pipeline proof** is part of `run.ps1 check`. On Windows, install Visual Studio Build
Tools with the **Desktop development with C++** workload, CMake, and OpenCV through vcpkg:

```bash
# in: REPO
# once, from a Developer PowerShell after cloning/bootstrapping vcpkg
$env:VCPKG_ROOT = 'C:\vcpkg'       # replace with your actual vcpkg folder

# in: REPO. CMake reads analysis\vcpkg.json and installs OpenCV+FFmpeg and ONNX Runtime.
cmake -S analysis -B analysis\build -DCMAKE_TOOLCHAIN_FILE="$env:VCPKG_ROOT\scripts\buildsystems\vcpkg.cmake"
cmake --build analysis\build --config Release
```

OpenCV is linked now for the video pipe proof. `analysis\vcpkg.json` also installs ONNX Runtime,
ready for the next step, but it is intentionally not linked until the RF-DETR inference module
exists; the plumbing proof should not depend on an unused runtime. Once `VCPKG_ROOT` is set,
`run.ps1 check` automatically uses the same toolchain.

**Regenerating fixtures.** Deterministic, so a clean regeneration changes nothing and CI fails
if it does:

```bash
# in: REPO
node fixtures\tools\generate_fixture.mjs --no-video   # data only, fast
node fixtures\tools\generate_fixture.mjs              # also re-renders the video, needs ffmpeg
```

---

## Hosting it

**There is nothing to deploy, and you should not put it on the public internet.**

The web app builds to static files, and the ingest service serves them, so one process on one
port gives you both:

```bash
# in: REPO
.\run.ps1 serve
```

It prints your LAN addresses. At a competition, run that on one laptop and everyone else opens
`http://<that-laptop-ip>:8080` on the venue wifi. If they cannot connect, Windows Firewall is
blocking it — allow `python.exe` on private networks.

Why not a real host: the service needs the database, the downloaded video files, yt-dlp and the
analysis binary, so it is not a static site. Video egress from a cloud host costs money for
files nobody outside the team needs. And doc 2 already notes that bulk downloading is against
YouTube's terms — running that as a public service turns a tolerated local tradeoff into
something with your name on it.

If you later want scouting numbers visible off the network, the Sheets export already does that
job: it is a shareable link with the aggregates and no video.

For access from outside the venue, Tailscale or ZeroTier gives the team a private network
without exposing anything publicly.

---

## When something goes wrong

**`Could not open requirements file`** — you are in `web\`. `cd` to REPO. Delete any
`web\ingest\` folder you created.

**`... is not recognized as the name of a cmdlet`** — missing `.\` on a relative program.

**Port already in use:**

```bash
Get-NetTCPConnection -LocalPort 5173 -State Listen | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }
```

**Jobs appear but no events, and the browser console says a module "does not provide an
export"** — Vite is holding a stale module graph, usually after a `git pull` changed files under
it. **Restart the dev server**; refreshing the page will not fix it. This looks exactly like a
code bug and is not one.

**Export returns 503** — correct when `SHEETS_SPREADSHEET_ID` and
`GOOGLE_APPLICATION_CREDENTIALS` are not both set. It refuses rather than reporting a write that
never happened.

**`alliances` and `tba_score` are null** — no `TBA_API_KEY`, or TBA has no data for that match.
Both are legal.

**A job failed** — read `error_code`, not just the message. It is a closed set and tells you
whether retrying helps: `rate_limited` yes, `video_unavailable` no.
