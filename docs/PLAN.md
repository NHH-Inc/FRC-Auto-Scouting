# The plan

Last updated 2026-08-30.

## You are here

Almost all the *software* is done. Almost none of the *data* exists.

```
[1] analysis  C++   ████████░░  builds and runs locally — but has NO trained detector
[2] ingest    Py    ██████████  works. Supabase connected, TBA verified, 30 tests + 71 checks green
[3] web       TS    ██████████  works. Player, overlay, corrections, Sheets export all done
    training  Py    ████████░░  every script is written and tested — nobody has run it on real data
    DATA            ░░░░░░░░░░  no videos, no collections, no reviewed labels, no model
```

`data/` is empty. That is the whole story. Everything below is about filling it.

## The one thing blocking everything

**There is no trained robot detector.** Without it, component 1 finds nothing, so component 2
stores nothing, so component 3 displays nothing. Every other task on this list is optional
polish until this is done.

And the detector is blocked on *labelled data*, which is blocked on *a human reviewing boxes*,
which is blocked on *someone downloading three match videos*. That's a four-link chain and we are
at link zero.

**So: the single highest-value thing anyone can do this week is download three FRC match videos
and run `extract` on them.** It takes about an hour and unblocks the other three links.

---

## Phase 1 — Get to a working detector

This is the only phase that matters right now. Everything is sequential; each step needs the one
before it.

### 1.1 — Download three or more different matches · **Justin** · ~1 hour

Different matches, not one long video. Different events if possible — different lighting and
camera operators make the model generalise.

```powershell
.\run.ps1 full
```

Paste three YouTube links into the UI, let them download. Then confirm you have segments:

```powershell
Get-ChildItem data\segments
```

**Done when:** three or more MP4s in `data\segments\`.

> Watch your disk. Downloads now refuse to start below 10 GB free, and `.\run.ps1 clean` reclaims
> completed jobs' video. A single unclipped VOD ate 9.2 GB once already.

### 1.2 — Extract frames and get proposals · **Justin** · ~1 hour, mostly waiting

Per [docs/TRAINING.md](TRAINING.md) step 1 and 2 — `extract`, then `auto-label`, once per match.
Save every collection path it prints.

**Done when:** three collection folders under `data\collections\`, each with
`model-consensus.jsonl`.

### 1.3 — Package for review · **Justin** · ~5 minutes

`export-coco` with all three collections at once and `--allow-unreviewed`.

**Done when:** `data\datasets\robot-v1\{train,valid,test}\_annotations.coco.json` all exist.

### 1.4 — Review the boxes · **Robert** · **the long pole — several hours**

Roboflow, one class `robot`, per [docs/TRAINING.md](TRAINING.md) step 3. This is the step no
script can do and the step that sets the ceiling on model quality.

**Done when:** a reviewed COCO folder with non-empty `train` and `valid`.

> If the classroom machines are available, this is the step to parallelise across them — it's
> browser-only, no GPU needed. Ask first (see 3.2).

### 1.5 — Train · **Robert (NVIDIA GPU)** · ~2 hours unattended

```powershell
.\training\run_rfdetr.ps1 -Dataset data\datasets\robot-v1-reviewed -Output data\models\robot-v1
```

**Done when:** `data\models\robot-v1\onnx\inference_model.onnx` exists.

### 1.6 — Plug it in and look at it · **anyone** · ~15 minutes

Copy `detector.local.json`, set `FRC_DETECTOR_CONFIG`, run a match the model has **never seen**.

**Done when:** boxes sit on robots in the overlay and disappear at camera cuts instead of sliding
across them. Judge by watching, not by mAP — see the "What good looks like" section in
[docs/TRAINING.md](TRAINING.md).

**When 1.6 passes, the project works end to end for the first time.** Everything after this is
improvement rather than construction.

---

## Phase 2 — Make the output trustworthy

Only start these once 1.6 passes.

| # | Task | Owner | Why it matters |
|---|---|---|---|
| 2.1 | **Scoreboard OCR** | Robert | Gives a trustworthy match start time. Independent of bumper OCR, so it can land first. The crop region must be per-video-source config — never hardcoded. |
| 2.2 | **Bumper OCR / team ID** | Robert | Turns "a robot" into "team 254". This is what makes the data *scouting* data rather than object detection. |
| 2.3 | **Accuracy check against TBA** | Justin | We have TBA working and scores available. Compare our extracted events to the real final score; that number is the honest measure of whether any of this works. |
| 2.4 | **More matches, `robot-v2`** | everyone | Same loop as phase 1, into a **new** output folder. Never overwrite v1. |

## Phase 3 — Operations

Independent of phases 1 and 2. Can happen in parallel any time.

| # | Task | Owner | Notes |
|---|---|---|---|
| 3.1 | **Google Sheets service account** | Robert | Create the Cloud service account, download the JSON key, share the sheet with its email as **Editor**, point `GOOGLE_APPLICATION_CREDENTIALS` at the file. Keep the JSON outside the repo. Everything else is already built — tabs are created automatically, sheet ID is already in `ingest/.env`. |
| 3.2 | **Ask about the classroom PCs** | Robert | Twenty machines with 5070 Tis. Cheap to ask; it's the difference between one training box and twenty labelling boxes. **Get explicit school permission, and do not bulk-download YouTube video on school hardware.** |
| 3.3 | **Decide where ingest runs** | Justin | Justin has said he'd rather not host it on his own PC. Options and trade-offs are in [docs/HOSTING.md](HOSTING.md). YouTube blocks datacentre IPs, which is the constraint that shapes the whole answer. |

## Phase 4 — Cheap experiments worth doing

Small, self-contained, and each one is genuinely uncertain — do them when you want a break from
the main line.

- **Is `gemma3:4b` earning its slot?** It takes image input but isn't trained for box grounding
  the way the two Qwen-VL models are — and those two are the same family, so gemma3 carries all
  the actual diversity in the ensemble. Per-model raw output is already saved, so this is ~20
  minutes on 50 frames using `compare-models`.
- **Try `iou_threshold: 0.40` instead of 0.50.** A robot in a wide field shot is often under 5% of
  frame width, where a few pixels of honest disagreement drops a real match below 0.5.
- **`jpeg_quality: 85` instead of 95** roughly halves frame storage with no meaningful detection
  loss.
- **SAM 3.1 as a second proposal source.** Optional, Robert's GPU only. Test on ten frames first
  and drop it if it doesn't clearly help — reviewed boxes are the goal, not a tour of foundation
  models.

---

## Nathaniel

Nathaniel is busy and his work moved to Robert. Nothing is assigned to him. If he frees up, the
best use of his time is **1.4 (reviewing boxes)** — it's the bottleneck, needs no setup, and
parallelises across as many people as want to help.

## Rules that hold across every phase

- Nothing in `/contracts/` changes without all three of us agreeing.
- Never commit `data/`, `ingest/.env`, ONNX weights, service-account JSON, or Hugging Face tokens.
- Never overwrite a model, a reviewed dataset, or raw model output. New version, new folder.
- Run `.\run.ps1 check` before you push. CI runs the same thing.
- When you change a model column, add the matching `ALTER TABLE` in `ingest/database.py` —
  `create_all()` only creates missing *tables*, never new columns on existing ones. The service
  now warns loudly at startup when the live schema has drifted.
