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
| 1.2 Extract frames + model proposals | Justin | done — 557 frames, three vision models each proposed boxes |
| 1.3 Package as COCO | Justin | done — `data/datasets/robot-poc-v1/` |
| **1.4 Review the boxes** | **you** | **← you are here** |
| 1.5 Train RF-DETR | you | after 1.4 |
| 1.6 Plug in and look at it | anyone | after 1.5 |

The ten matches come from ten different events on purpose. Frames from one match must all stay in
the same train/valid/test split, so each match is one indivisible group — and ten venues means ten
different lighting setups, camera operators and field conditions, which is what stops the detector
from memorising one arena.

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

Three local vision models (`qwen3-vl:4b`, `qwen2.5vl:7b`, `gemma3:4b`) each looked at every frame
and guessed. Where they agreed — boxes overlapping by 40% or more — that became the consensus
draft you are reviewing.

**They are guesses.** Every row is marked `human_review_required: true`. Expect them to be wrong
often; the point is that fixing a rough box is faster than drawing one from nothing.

Two things worth knowing:

- Some frames have proposals from only two models. `qwen2.5vl:7b` sometimes falls into a
  repetition loop — emitting the same box over and over until it hits the token limit and the
  JSON truncates. Those are recorded as `status: "failed"` with empty boxes and excluded from the
  vote, so a failure never counts as "this model saw no robots". The frame is still perfectly
  usable; it just had a two-model panel.
- `gemma3:4b` may not be earning its slot. It takes image input but is not trained for bounding-box
  grounding the way the two Qwen models are — and those two are the same family, so gemma3 carries
  all the actual diversity in the ensemble. `model-comparison.json` in each collection has the
  numbers. Worth 20 minutes of your time at some point, but not before the review.

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
