# The plan

Last updated 2026-08-31.

## You are here

The software is done and the pipeline has been proven end to end on real footage. What is left is
the part only a person can do.

```
[1] analysis  C++   █████████░  builds locally, verified on real 2026 broadcast - no trained detector
[2] ingest    Py    ██████████  works. Supabase connected, TBA verified, 30 tests + 71 checks green
[3] web       TS    ██████████  works. Player, overlay, corrections, Sheets export all done
    training  Py    ████████░░  scripts written and tested - not yet run on real labels
    DATA          ███████░░░  10 matches downloaded, 557 frames extracted and proposed
```

**Steps 1.1 to 1.3 are done.** Justin's part of phase 1 is finished. The dataset is waiting for
review — see [REVIEW-HANDOFF.md](REVIEW-HANDOFF.md), which is the page Robert should open.

What was proven along the way:

- The C++ analyzer decodes a real 2026 broadcast (12,864 frames of `2026tuis_qm29`) and correctly
  emits **zero tracks** with no detector configured. It invents nothing.
- The full API path works on real video: job listed, served, correct Contract E envelopes,
  `box_sample_rate` present, no invented tracks. 8/8 checks.
- Ten matches from **ten different events** in the 2026 REBUILT season, so every match is an
  independent split group with its own venue, lighting and camera operator.

## The one thing blocking everything

**There is no trained robot detector**, and now the only thing standing between us and one is
step 1.4: a human looking at 557 frames and fixing the boxes.

Component 1 finds nothing, so component 2 stores nothing, so component 3 shows nothing. Every
other task is optional polish until that is done.

## What we learned the hard way: the local VLM ensemble does not scale

Worth reading before anyone plans around it. Measured on Justin's RX 7800 XT with all weights
resident in VRAM, using the real grammar-constrained prompt:

| model | per frame | boxes | reliability |
|---|---|---|---|
| `gemma3:4b` | 17.2s | 6 | fine |
| `qwen3-vl:4b` | 63.1s | 8 | fine |
| `qwen2.5vl:7b` | 95.1s | — | **fails constantly** (repetition loop, retry included) |

All three across 557 frames projects to **42 hours**. The proof-of-concept run therefore uses
`configs/data_collection.poc-fast.yaml` — `gemma3:4b` alone, ~2.7 hours for the same frames.

Three things follow:

1. **The agreement signal is gone.** With one model there is nothing to agree with, so
   `iou_threshold` does nothing and every box is a single unverified opinion. Treat the proposals
   as a drawing head start, not as a vote.
2. **The question in phase 4 is inverted.** The docs asked whether `gemma3:4b` earns its slot as
   a third vote. On this hardware it is the *only* model that finishes. That says nothing about
   its accuracy — it is still the model least suited to box grounding — but the ensemble as
   designed cannot run here.
3. **A short benchmark lied by 16x.** Timing with "how many robots?" suggested 17s per frame for
   all three models. The real call generates a multi-box JSON under a schema constraint —
   hundreds of output tokens, not two. Benchmark the actual call or do not bother.

If the classroom machines come through, running the full ensemble across many machines is exactly
what they would be good for.

---

## Phase 1 — Get to a working detector

This is the only phase that matters right now. Everything is sequential; each step needs the one
before it.

### 1.1 — Download matches · **Justin** · DONE

Ten qualification matches, one each from **ten different 2026 events** — İstanbul, Canadian
Pacific, Lake Superior, Northern Lights, Minnesota Bluff Country, Oklahoma, Brazil, Pikes Peak,
PCH Dalton, FIM Lakeview. About 3.5 minutes each, 1.0 GB total, all real REBUILT footage found
through TBA's match video listings.

One match per event on purpose: a match is an indivisible split group, so ten venues means ten
independent groups with different lighting, camera operators and field wear.

> Disk guards are live. Downloads refuse to start below 10 GB free, and `.\run.ps1 clean`
> reclaims completed jobs' video after the grace window.

### 1.2 — Extract frames and get proposals · **Justin** · DONE

557 frames at 0.25 fps (`configs/data_collection.poc.yaml`), then `gemma3:4b` proposals via
`configs/data_collection.poc-fast.yaml`.

The sampling rate is deliberate. At the default 2.0 fps these ten matches would have produced
several thousand frames half a second apart — near-duplicates that cost review time and teach the
detector nothing new. 557 frames that actually differ is a better dataset *and* a reviewable one.

Single model rather than the three-model ensemble, for the reasons in the table above. The
proposals are therefore a **drawing head start, not a vote** — no agreement signal exists.

### 1.3 — Package for review · **Justin** · DONE

`export-coco` across all ten collections with `--allow-unreviewed`, producing
`data/datasets/robot-poc-v1/` with `train`, `valid` and `test` splits assigned at match
granularity.

`--allow-unreviewed` is required here and nowhere else: it records in the command itself that
these labels are model proposals, not ground truth.

### 1.4 — Review the boxes · **Robert** · ⬅ **NEXT. The long pole.**

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
- **SAM, if a machine can run it.** Note that this needs SAM **3**, not SAM 2: the integration
  works by text prompt ("FRC competition robot"), and text prompting is a SAM 3 feature. SAM 2
  takes only points/boxes/masks, so it cannot stand in.
- **SAM 2 video tracking — a different, probably better idea.** Draw boxes on one frame, let SAM 2
  propagate them through the match, sample at our frame timestamps. That converts per-frame
  labelling into per-match labelling. Nobody has built it; it has to run on the source MP4s rather
  than the 4-second-spaced frames, and camera cuts and robot-on-robot occlusion both break
  tracking. Worth doing for the real season dataset, not for a proof of concept that is already
  labelled. SAM 2 is also Apache 2.0 with no Hugging Face gating, unlike SAM 3.1.

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
