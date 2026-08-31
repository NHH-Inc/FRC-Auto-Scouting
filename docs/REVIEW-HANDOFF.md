# Robert — start here

**You do not have to review 554 frames.** This is a proof of concept that gets deleted and
retrained when the season starts (decision P3 in [DECISIONS.md](DECISIONS.md)), so there is a
zero-effort path and it is a legitimate choice.

Pick one:

| | Your time | What you get |
|---|---|---|
| **A. Train now, review nothing** | **0 min** | Use `robot-poc-v1-autofiltered`. Impossible labels already removed by script. |
| **B. Spot-check ~50 frames first** | ~25 min | Same dataset, but you'd know whether it is worth showing. |
| **C. Full review** | hours | The real thing. Save it for the season dataset. |

**Take A unless you want to.** Justin already ran the filtering; the dataset is sitting there.

---

## What already happened

| Step | Who | Status |
|---|---|---|
| 1.1 Download match videos | Justin | done — 10 matches, 10 different events, 2026 REBUILT season |
| 1.2 Extract frames + model proposals | Justin | done — 554 frames, one vision model |
| 1.3 Package as COCO | Justin | done — two datasets, see below |
| 1.4 Review | **optional now** | skip it for the demo |
| **1.5 Train RF-DETR** | **you** | **← start here** |
| 1.6 Plug in and look at it | anyone | after 1.5 |

Ten matches from ten different events on purpose: frames from one match must all stay in the same
train/valid/test split, so each match is one indivisible group. Ten venues means ten lighting
setups and camera operators, which is what stops the detector memorising one arena.

## The two datasets

Both are on Justin's machine under `data/`, which is git-ignored. Get the folder from him.

| Folder | Frames | Boxes | Use it when |
|---|---|---|---|
| `robot-poc-v1-autofiltered` | 447/53/54 | **2,027** | **Default. Train on this.** |
| `robot-poc-v1` | 447/53/54 | 2,843 | Only if you want the raw, unfiltered proposals |

### What the filter removed, and what it could not

A script (`ingest/collection/sanity_filter.py`) dropped labels that are *impossible*, without
anybody looking at a frame:

- **71 frames proposed more than 8 boxes.** An FRC field has six robots. A frame claiming nine is
  wrong about at least three, and there is no way to know which three — so the whole frame stops
  claiming to be labelled rather than having three boxes deleted at random.
- **6 boxes covered more than a quarter of the frame.** That is the field or a replay close-up,
  not one robot.

That is 71% of boxes kept across 483 still-labelled frames.

**The filter cannot catch a box that is simply wrong** — on the wrong object, too loose, or a
robot missed entirely. Only a human sees that. So everything here is still an unverified guess,
and the model you train will imitate those guesses, mistakes included.

**For a demo that is fine.** For the season it is not, and nobody should pretend otherwise.

## What the proposals actually are

**One** local vision model (`gemma3:4b`) looked at every frame and guessed. Every box carries
`agreement_count: 1` and `source: "model_single"` — one model's unverified opinion, with no
second model agreeing.

Why one model when the design called for three, measured on Justin's GPU with the real prompt:

- `qwen2.5vl:7b` — 95s/frame **and fails constantly** (repetition loop; truncates its own JSON)
- `qwen3-vl:4b` — 63s/frame, works
- `gemma3:4b` — 17s/frame, reliable

All three across these frames projects to **42 hours**. One model did it in 77 minutes. The irony
is on the record: the docs single out `gemma3:4b` as the model *least* suited to box grounding,
and it is the only one that finishes on a single machine.

If the classroom PCs come through, the real three-model ensemble across twenty machines is about
two hours — and then model agreement would actually mean something.

## A note on what the demo is really showing

The detector is the least finished part of this project, and it is also not the interesting part.
What works properly today is the overlay tracking robots frame-accurately, corrections that never
overwrite raw model output, TBA integration, and the Sheets export.

If the boxes look rough in the demo, **that is a feature you can show**: open a bad box, correct
it in the UI, and point out that `?raw=true` still returns exactly what the model said. Being able
to fix the model without destroying its output is a real design decision, not a patch over a
weakness.

## Then train

On your NVIDIA machine, from the repo root:

```powershell
.\training\run_rfdetr.ps1 -Dataset data\datasets\robot-poc-v1-autofiltered -Output data\models\robot-poc-v1
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
