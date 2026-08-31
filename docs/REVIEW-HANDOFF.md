# Robert — start here

Justin's steps are done. A labelled-proposal dataset is sitting on his machine waiting for you.
This document is the whole job.

**Your job is step 1.4 in [PLAN.md](PLAN.md): look at proposed robot boxes and decide whether
they are right.** Nothing else is blocked on you until that is finished.

---

## What already happened

| Step | Who | Status |
|---|---|---|
| 1.1 Download match videos | Justin | done — 10 matches, 10 different events, 2026 REBUILT season |
| 1.2 Extract frames + model proposals | Justin | done — 554 frames, one vision model proposed boxes |
| 1.3 Package as COCO | Justin | done — `data/datasets/robot-poc-v1/` |
| **1.4 Review the boxes** | **you** | **← you are here** |
| 1.5 Train RF-DETR | you | after 1.4 |
| 1.6 Plug in and look at it | anyone | after 1.5 |

The ten matches come from ten different events on purpose. Frames from one match must all stay in
the same train/valid/test split, so each match is one indivisible group — and ten venues means ten
different lighting setups, camera operators and field conditions, which is what stops the detector
from memorising one arena.

## What you are actually getting

Measured across all 10 matches, not estimated:

| | |
|---|---|
| Frames to review | **554** |
| Frames with at least one proposed box | 496 (89%) |
| **Frames with nothing on them** | **58 (10%)** — you draw these from scratch |
| Proposed boxes total | 2843 |
| Distinct boxes | 2087 of 2843 — real variety, not one guess repeated |
| Median box size | 3.8% of frame |
| Median aspect ratio | 0.63 (taller than wide, as robots are) |
| Model calls that failed outright | 3 |

The most common non-empty answer is **6 boxes on a frame**, which is exactly how many robots are
on an FRC field — a sign the model is genuinely looking at least some of the time. 89% of frames
came back with something on them, and 2,087 of the 2,843 boxes are distinct, so this is not one
guess stamped everywhere.

That said, **none of it is verified.** Expect wrong boxes, boxes on the score overlay, missed
robots, and the occasional frame with an absurd count. The proposals are a head start on drawing,
not a first pass at correctness — your job is still to check every one.

## Read this before you start clicking

**This dataset is disposable.** It gets deleted when the competition season starts, and the
detector gets retrained from fresh footage — see decision P3 in [DECISIONS.md](DECISIONS.md). You
are proving the pipeline works end to end, not building the model that ships.

Practically, that means: **review well enough to prove the loop closes, then stop.** Do not
perfect this. If a frame is ambiguous, exclude it rather than agonising over it.

## Getting the data

The frames live on Justin's machine under `data/`, which is git-ignored — none of it is in the
repo, and none of it should be. Get the `data/datasets/robot-poc-v1/` folder from him directly
(it is a few hundred MB).

## What to do in Roboflow

1. Create a **private Object Detection** project called `FRC Robot Boxes`.
2. Create exactly one class: `robot`. No team numbers, no goals, no event types. Team ID is a
   separate classifier later — mixing it in now makes both problems harder.
3. Upload the three folders — `train`, `valid`, `test` — **preserving those split names**. Pick
   **COCO JSON** if it asks for a format.
   > Do not let Roboflow re-shuffle the splits. The split assignment already respects match
   > boundaries; re-shuffling would put frames from one match on both sides and quietly inflate
   > the accuracy number.
4. Go through the frames:
   - **Delete** boxes on people, field elements, the score overlay, and robots shown on a screen.
   - **Add** every robot the models missed.
   - **Tighten** each box to one whole robot, bumper included.
   - **Exclude** replay close-ups and camera-cut blur instead of labelling them badly. A wrong
     label is worse than no label — it actively teaches a mistake.
5. Export in **COCO JSON** to `data/datasets/robot-poc-v1-reviewed`.

Check these exist before moving on:

```text
data\datasets\robot-poc-v1-reviewed\train\_annotations.coco.json
data\datasets\robot-poc-v1-reviewed\valid\_annotations.coco.json
```

## What the proposals actually are

**One** local vision model (`gemma3:4b`) looked at every frame and guessed. The three-model
ensemble was the plan, but it projects to 42 hours on one machine — see [PLAN.md](PLAN.md).
So there is no agreement signal here: every box carries `agreement_count: 1` and
`source: "model_single"`, meaning one model's unverified opinion.

**They are guesses.** Every row is marked `human_review_required: true`. Expect them to be wrong
often; the point is that fixing a rough box is faster than drawing one from nothing.

Why only one model, when the design called for three:

- `qwen2.5vl:7b` takes 95s per frame **and fails constantly** — it falls into a repetition loop,
  emitting the same box until it hits the token limit and truncates its own JSON. Even with a
  retry on a different seed it mostly does not recover.
- `qwen3-vl:4b` works but takes 63s per frame.
- `gemma3:4b` takes 17s and is reliable.

All three across these frames projects to **42 hours**. One model did it in 77 minutes. Three of
2,843 calls failed outright, and those are recorded as `status: "failed"` with empty boxes rather
than being silently dropped.

The irony is worth knowing before you trust anything: the docs single out `gemma3:4b` as the
model *least* suited to box grounding, and it is the only one that finishes on one machine. If
the classroom PCs come through, running the real three-model ensemble across them is exactly what
they would be good for — and then agreement between models would actually mean something.

## Then train

On your NVIDIA machine, from the repo root:

```powershell
.\training\run_rfdetr.ps1 -Dataset data\datasets\robot-poc-v1-reviewed -Output data\models\robot-poc-v1
```

It builds its own environment, installs RF-DETR and CUDA dependencies, trains RF-DETR Small at
640px, and exports ONNX. Roughly two hours unattended.

Done when `data\models\robot-poc-v1\onnx\inference_model.onnx` exists.

Full explanation of what training is and why each rule exists: [TRAINING.md](TRAINING.md).

## Then look at it

```powershell
Copy-Item analysis\config\detector.example.json analysis\config\detector.local.json
# point model_path at the ONNX file, then:
$env:FRC_DETECTOR_CONFIG = (Resolve-Path "analysis\config\detector.local.json").Path
.\run.ps1 full
```

Queue a match the model has **never seen**. Judge it by watching the overlay, not by the accuracy
number: do boxes sit on robots, and do they disappear at camera cuts instead of sliding across
them? A great mAP with drifting boxes means split leakage, not a good model.

The C++ side is already built and verified against real 2026 broadcast footage — it decoded a full
match (12,864 frames) and correctly emitted zero tracks with no detector configured. So if you see
no tracks after pointing it at your model, the problem is the config path, not the analyzer.

## Never commit

```text
data\                                 videos, frames, datasets, weights
analysis\config\detector.local.json
ingest\.env                           Supabase URL and API keys
training\.venv\
Hugging Face tokens, Google service-account JSON
```

## The other two things you own

Both independent of the review — do them whenever, they are not blocked:

- **Google Sheets service account** (3.1 in [PLAN.md](PLAN.md)). Create it in Google Cloud,
  download the JSON key, share the spreadsheet with the service account's email as **Editor**,
  point `GOOGLE_APPLICATION_CREDENTIALS` at the file. Keep the JSON outside the repo. Everything
  else is built — the tabs create themselves and the sheet ID is already in `ingest/.env`.
- **Ask about the classroom PCs** (3.2). Twenty machines with 5070 Tis. Cheap to ask, and it is
  the difference between one labelling person and twenty — the review step is browser-only and
  parallelises perfectly. **Get explicit school permission first, and do not bulk-download
  YouTube video on school hardware.**
