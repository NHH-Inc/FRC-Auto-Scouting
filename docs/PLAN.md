# The plan

Last updated 2026-09-01.

## You are here

Waiting on one training run. Everything else is built.

```
[1] analysis  C++   █████████░  builds and runs on real broadcast - no trained detector yet
[2] ingest    Py    ██████████  works. 66 tests, 71 contract checks green
[3] web       TS    ██████████  player, overlay, corrections, Sheets export
    labelling Py    ██████████  quality filter, box fusion, detect runner - all tested
    DATA            █████████░  2,429 labelled images + 3,077 usable frames, no model
```

**Robert has the training data and is training.** When his weights come back, one command labels
our footage and the loop closes.

## The plan changed twice, and both times for a reason

The original route was: one small vision model guesses boxes, a human fixes all 554, train on the
result. Two things killed it.

**The guesses were not localisation.** A single box size accounted for 23% of every box the model
drew, and it put "robots" on the FIRST logo. It was stamping a template, not measuring anything,
so its ceiling was low however much a human corrected afterwards.

**Better data already existed.** Two community datasets on Roboflow Universe, both CC BY 4.0,
together give **2,429 human-labelled FRC robot images** — more and better than we were going to
produce, at the cost of a download.

So the shape now is: train on other people's labels, use that model to label our footage, fuse
several detectors to get a confidence worth trusting. That also breaks the circular problem that
blocked everything — YOLO11 and RF-DETR both ship pretrained on COCO, which has no `robot` class,
so neither could label FRC robots until something taught one what a robot is.

## What exists now

| | |
|---|---|
| `data/datasets/frc-robots-merged/` | 2,429 labelled images, one `robot` class, splits rebuilt |
| `data/collections/` | 3,077 usable frames, 50 matches, 25 venues |
| `data/segments/` | 4.6 GB source video |
| `frame_quality.py` | rejects broadcast graphics, recalibrated on 25 venues |
| `dataset_merge.py` | collapses third-party datasets to one class, fixes their leaks |
| `box_fusion.py` | confidence recomputed from agreement, weights learned from evidence |
| `detect_runner.py` | ONNX inference + fusion over a collection |

## Two things learned that should not be relearned

**Both source datasets leaked across their own splits.** Roboflow assigns augmented copies of one
photograph to train/valid/test independently, so a flipped version of a validation image trains
the model. WorBots' published mAP@50 of 97.6% is inflated by this. We regrouped by source image;
expect a lower and more honest number.

**Thresholds tuned on ten venues did not survive twenty-five.** The frame filter rejected 94% of
one match — all of it real gameplay — because that arena has a uniform grey floor. Calibrate on
the widest sample available, and check the extremes by eye before trusting a filter.

---

## Phase 1 — Get to a working detector

This is the only phase that matters right now. Everything is sequential; each step needs the one
before it.

### 1.1 — Match footage · **Justin** · DONE

50 qualification matches from **25 different 2026 events**, 4.6 GB. Two per venue, spaced within
each event so the pair does not share lighting and field state. One match is one indivisible split
group, so venue count is what buys generalisation.

### 1.2 — Frames, filtered · **Justin** · DONE

3,300 frames at 0.25 fps, of which **3,077 are usable**. The rest are FIRST logos, sponsor stings,
"ALLIANCE WINS" cards and score screens, rejected by `frame_quality.py` before any model sees them.

### 1.3 — Training data · **Justin** · DONE

Not our own guesses, in the end. Two CC BY 4.0 datasets from Roboflow Universe merged down to a
single `robot` class: **2,429 human-labelled images**, 5,815 boxes, at
`data/datasets/frc-robots-merged/`. Their splits leaked and were rebuilt; see the notes above.

### 1.4 — Train a labeller · **Robert** · IN PROGRESS

```powershell
yolo detect train data=<path>/frc-robots-merged/data.yaml model=yolo11s.pt epochs=100 imgsz=640
yolo export model=runs/detect/train/weights/best.pt format=onnx
```

Send back the **ONNX** — about 20 MB. Send the model, never the frames: our frame set is several
GB and the model is not.

**Done when:** a `.onnx` file exists and its boxes land on robots in a match it never saw.

### 1.5 — Label our footage · **Justin** · ~30 min once weights arrive

Run the ONNX over the 3,077 usable frames and fuse. `detect_runner.py` does both; the fusion
recomputes each box's confidence from how much detector weight backs it, how tightly the backers
agree, and how reliable each detector has proven across the collection.

With one detector there is no agreement signal, so a second source is what makes the confidence
mean anything. RF-DETR trained on the same merged dataset is the obvious second.

**Done when:** `detector-consensus.jsonl` exists per collection, and the top-ranked boxes are on
robots rather than on the score bar.

### 1.6 — Plug it into the analyzer and watch · **anyone** · ~15 min

Point `detector.local.json` at the ONNX, set `FRC_DETECTOR_CONFIG`, run a match nothing has seen.

Judge by watching, not by the accuracy number. Do the boxes sit on robots? Do they disappear at
camera cuts instead of sliding across them? A high mAP with drifting boxes means leakage, not a
good model — and we already know both source datasets leaked before we rebuilt their splits.

**Done when:** boxes track robots through a real match and gap at broadcast cuts.

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
