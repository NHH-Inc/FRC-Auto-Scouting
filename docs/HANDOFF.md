# Handoff

Everything a person or an AI assistant needs to pick this project up cold. If you are being
dropped into this repo with no history, read this file top to bottom and you will know as much
as anyone.

Last updated 29 Aug 2026, at `SCHEMA_VERSION 3`.

---

## 1. What the project is

A tool that watches recorded FRC match video and produces **per-robot** scouting data. Match
totals are already free and exact from The Blue Alliance; the only reason to do video analysis is
what TBA does *not* have — which of the three robots on an alliance did what, how long its cycles
took, how accurate it was, where it spent its time.

Three components, one repo, **no cross-imports**:

```
[3] web  ──HTTP──▶  [2] ingest  ──exec──▶  [1] analysis
                         │                      │
                         ├── yt-dlp             └── events.jsonl
                         ├── TBA API                tracks.jsonl
                         └── database               result.json
```

Component 3 only ever talks to component 2 over HTTP. Component 2 runs component 1 as a
command-line binary. **Components 1 and 3 never touch each other.**

`docs/frc-scouting-0-contract.md` is the shared contract and is **normative** — where it and
documents 1, 2 or 3 disagree, doc 0 wins. Documents 1 and 3 used to print an eight-field event
row that is wrong; they have been corrected, but if you find that row anywhere else, ignore it.

---

## 2. Where it actually stands

| | Status | Owner |
|---|---|---|
| Web app: player, overlay, corrections, timeline, stats, heat map, export | **works** | Justin |
| Ingest: yt-dlp, TBA, job queue, database, full Contract E API | **works** | Robert |
| Ollama labelling ensemble (3 local vision models, IoU consensus) | **works** | Robert |
| Google Sheets export | **works**, needs a service account JSON | Robert |
| **Analysis backend: detection, tracking, OCR** | **real-video pipe proof; no detector yet** | **Robert** |
| Human review of auto-labels | **not built** | Robert |
| Detector training | **not built** | Robert |

**The critical path is the analysis backend.** The binary now opens a real segment with OpenCV,
counts decoded frames, and emits one explicit diagnostic hand-placed track. That validates ingest
→ binary → database → API → overlay. There is still no detection pipeline; the diagnostic box is
not scouting output and must be replaced by the detector/tracker path.

Nathaniel originally owned component 1; he is busy, so **Robert now owns components 1 and 2.**

---

## 3. Running it

One script. It resolves paths relative to itself, so **it does not matter which folder you run it
from** — that was the single most common failure before it existed.

```bash
.\run.ps1 setup     # first time. venv, npm install, .env. Safe to re-run.
.\run.ps1 doctor    # what is installed, missing, or misconfigured
.\run.ps1 web       # UI on fixture data. No backend, no Python, no config.
.\run.ps1 full      # ingest + UI wired together (writes web\.env.local for you)
.\run.ps1 serve     # build the UI and serve everything on one port
.\run.ps1 check     # everything CI runs. Do this before pushing.
```

Start with `.\run.ps1 web`. It gives you the whole UI on a real 152-second fixture match with
boxes, 224 events, working corrections and a deliberately failed job so the retry path is
reachable. Nothing is mocked — it serves real fixture files through the same interface the HTTP
client uses.

**PowerShell specifics** that catch everyone:

- A relative program needs `.\` in front: `.\run.ps1`, not `run.ps1`.
- Env vars are `$env:NAME = 'value'`. There is no `NAME=value command` form.
- Do not use `$ErrorActionPreference = 'Stop'` around native exes. In 5.1 anything written to
  stderr becomes an ErrorRecord, so a harmless deprecation warning aborts your script even at
  exit code 0.

`docs/RUNNING.md` has the long version, including the Ollama labelling workflow and
troubleshooting. `docs/HOSTING.md` covers where to host it and where every kind of data lives;
`docs/CENTRAL-SETUP.md` covers running one shared instance the whole team works against — short version: **one ingest service, everyone else opens a URL**, and nobody
but the host needs a `.env` or database access.

---

## 4. The rules that keep getting rediscovered

These are doc 0 invariants. Every one of them has already caused a real bug.

**The event row has 14 fields.** Documents 1 and 3 once listed eight. Missing `event_id` means
corrections have nothing to reference; missing `source` means a model guess and a human fix are
indistinguishable, which breaks both the accuracy comparison and the training export.

**Corrections never overwrite model output.** A correction is a new row referencing what it
changed. Reads apply them; `?raw=true` returns untouched model output. This was violated once —
`PATCH` mutated the event in place — and it is unrecoverable data loss, because a correction
records the new value, not the old one.

**Tracks carry a required `gaps` array,** and you must not interpolate across one. A gap is an
interval where the robot was *not observed*. Without it a four-second hole is indistinguishable
from a low sample rate and the overlay draws a robot gliding through footage nobody analysed.
**Do not split a track at a gap** — re-identification exists to stitch fragments into one logical
track, and splitting undoes it.

**Phase is derived, never detected.** A pure function of match-relative time and the season
config. Both components compute it from the same file so they cannot disagree. Nobody hardcodes
15, 135 or 20.

**`goal` is not a closed set.** Legal values are the `goals` array of
`contracts/seasons/<year>.json`, because they change every January. Validate against that file,
not against a list in doc 0.

**Aggregates are never stored, only queried.** Every stat is a query over the event table.

**Point values are zero placeholders** until the 2026 game is public. Score reconstruction is
meaningless until then and the UI says so. **Do not invent values to make a test pass.**

**A contract change is a conversation, not a commit.** It needs all three of us and a
`SCHEMA_VERSION` bump. Additive changes (a new optional field) stay backward compatible; renames
and type changes require all three components to move together.

---

## 5. What is decided

`docs/DECISIONS.md` has 22 entries tagged settled / default / blocked. The ones you are most
likely to trip over:

- **IoU consensus, not coordinate averaging.** Averaging fails silently — one model missing the
  robot drags the box onto empty carpet with nothing in the output to show it.
- **Store frame references, not images.** 100k labelled frames is ~15 MB as
  `(video_id, start_offset, frame_number)` + boxes, versus 20–50 GB as JPEGs. Neither machine has
  50 GB spare.
- **The correction UI is the label source** for team identification. It already produces
  human-confirmed `(track → team)` pairs, reviewed by construction, growing as people scout.
- **Roboflow** for the dataset and the review UI. Not Google Drive: per-file overhead, rate
  limits, no random access.
- **Segments are deleted after analysis**, 7-day grace. The events are the product; media is a
  cache.
- **Nathaniel's model is a classifier** over robot crops, trained separately from the detector.
- **Hosting: nothing is deployed.** `run.ps1 serve` puts the API and UI on one port; at a
  competition one laptop runs it and everyone opens its LAN IP. Not public — it needs the
  database, the video and the analysis binary, and doc 2 notes bulk downloading is against
  YouTube's terms.

---

## 6. Hardware

| Machine | Silicon | Free disk | Role |
|---|---|---|---|
| Justin | 7800X3D · RX 7800 XT 16 GB · 32 GB | 107 GB | Ingest service, VLM labelling, web app |
| Robert | RTX 3060 **12 GB** · CUDA | 40 GB | Training, and now components 1 and 2 |
| Classroom | 20× RTX 5070 Ti 16 GB · 7700X · 32 GB | 800 GB | Best compute available — permission not yet asked |

**Justin cannot train.** PyTorch has no AMD support on Windows; the ROCm wheels are Linux-only,
and nobody has a usable Linux box. Ollama *does* support RDNA3 on Windows, so labelling runs
GPU-accelerated on his card.

**Disk is the binding constraint, not the GPU.** A full event VOD is 15–25 GB; one clipped match
segment is 300–600 MB. Clipping match windows is what makes this fit at all.

On the classroom machines: ask before counting on them, assume nothing survives a reboot, and
**do not download video on school infrastructure** — doc 2 accepts the terms-of-service tradeoff
for our own machines, but extending it to school equipment makes it the school's exposure, which
is not ours to decide. Download at home, carry segments in.

---

## 7. What is left

### Robert — component 1 is the whole project right now

1. **Build the detection pipeline.** Everything else runs on synthetic fixtures until this looks
   at a real video. The contract surface is already written and green in CI:
   `analysis/src/ContractModels.h` is at v3 with a `std::optional` serializer, and `main.cpp`
   parses `--job/--season/--out` and reports progress and error codes correctly. What is missing
   is detection, tracking, homography, OCR and event extraction.
2. Build from **Contract B in doc 0**, not doc 1's old field list. Emit `gaps` on every track.
   Read phase boundaries from the season config passed via `--season`.
3. **You are now on both sides of the Contract D boundary.** Resist making the two sides match
   each other instead of matching doc 0 — component 3 is written against the contract, and CI
   checks the binary's output against it independently.
4. Measure whether `gemma3:4b` is contributing a real vote to the ensemble. It takes image input
   but is not trained for bounding-box grounding the way the two Qwen-VL models are, and since
   those two share a family, gemma3 carries all the actual diversity. You already keep per-model
   raw output, so this is ~20 minutes on 50 frames.
5. Try `iou_threshold: 0.40` rather than 0.50. A robot in a wide field shot is often under 5% of
   frame width, where a few pixels of honest disagreement drops a real match below 0.5.
6. `jpeg_quality: 85` instead of 95 roughly halves your frame storage with no meaningful loss for
   detection training. You have 40 GB.

### Robert — also owns everything below, in this order

7. **Google Sheets export.** Create a Google Cloud service account, download its JSON key,
   share the spreadsheet with the service account's email as **Editor**, and point
   `GOOGLE_APPLICATION_CREDENTIALS` at the file. Keep that JSON outside the repo. Everything
   else is done; the tabs are created automatically. Sheet id is already in `ingest/.env`.
8. **Ask about the classroom machines.** Cheap to ask, and it is the difference between one
   training box and twenty labelling boxes.
9. **Roboflow setup**, which is also the human-review step.
10. **The detector trainer.** RF-DETR (Apache 2.0 — not Ultralytics, which is AGPL-3.0 and
    needs a paid licence for closed source), 640px, normal batch size on 12 GB.

**The ordering matters more than usual here**, because it is all one person. Items 1–6 come
first: everything downstream is on synthetic fixtures until the detection pipeline runs, and
Roboflow and the trainer have nothing to work on until there are labels to put in them.
Items 7 and 8 are ten-minute tasks that can fill a gap.

### Justin

1. Keep running the ingest service and the web app.
2. Component 3 is done; the next thing it needs is real analysis output to render.

### A note on the split

Robert now owns components 1 and 2, the labelling ensemble, review, training and the export
credentials. That is nearly the whole project on one person, and it is a single point of
failure worth naming out loud. See DECISIONS O2.

### Waiting on the world

- **Point values and real goal names** land when the 2026 game is public. Both change together,
  as one migration.

---

## 8. Gotchas that cost real time

- **Vite serves a stale module graph** after a `git pull` changes files under it. Symptom: the UI
  loads, jobs appear, but there are no events, and the console says a module "does not provide an
  export". **Restart the dev server** — refreshing does nothing. This looks exactly like a code
  bug and is not one.
- **`Could not open requirements file`** means you are in `web\`. Use `run.ps1`, which does not
  care where you are. Delete any `web\ingest\` folder a previous attempt created.
- **A partial `.env` fails honestly.** The Sheets export returns 503 rather than reporting a write
  that never happened. That is correct behaviour, not a bug.
- **`alliances` / `tba_score` null** is legal — no API key, or TBA genuinely has no data.
- **Read `error_code`, not the message.** It is a closed enum and tells you whether retrying
  helps: `rate_limited` yes, `video_unavailable` no.
- **Never commit `ingest/.env`** or the Google service account JSON. Both are gitignored; verify
  with `git check-ignore -v <path>` if unsure.

---

## 9. Where things live

```
analysis/     C++ component 1. ContractModels.h is the contract surface.
ingest/       Python component 2. main.py is Contract E. collection/ is the labelling ensemble.
web/          TypeScript component 3. src/contracts/ is the only place snake_case exists.
contracts/    Shared schemas + per-year season configs. Owned by everyone.
fixtures/     Golden test data, generated deterministically by fixtures/tools/.
docs/         The four context documents, DECISIONS.md, RUNNING.md, this file.
run.ps1       One entry point for everything.
```

Verification, all of which CI also runs:

```bash
.\run.ps1 check
```

That is 71 Contract E checks against the fixtures, 12 unit tests, 243 fixture records validated
against the schemas, a typecheck, a build, and a check that regenerating the fixtures changes
nothing. If it is green, you have not broken the contract.
