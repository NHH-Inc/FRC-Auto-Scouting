# Who does what next

The job changed. It is no longer "review 554 frames by hand" — that was the plan when the only
labels we had were one small model's guesses. We now have **2,429 human-labelled FRC robot
images** from two community datasets, which is a far better starting point than anything we were
going to produce.

**Robert trains. Justin runs the trained model over our footage.** Neither of you reviews frames
by hand for this round.

---

## The handoff, in one line

```
Justin  --[ 163 MB dataset ]-->  Robert  --[ ~20 MB weights ]-->  Justin
```

Send the **dataset** one way and the **weights** back. Do not send frames back and forth: the
dataset is 163 MB, trained weights are about 20 MB, and our 50-match frame set is several GB.
Moving the model is a hundred times cheaper than moving the images.

---

# Justin

## 1. Give Robert exactly one folder

```
data/datasets/frc-robots-merged/          163 MB
```

That is the whole handoff. It is git-ignored, so it will not arrive via `git pull` — put it on
Drive and send the link. Everything else he needs is in the repo.

Inside it:

```
train/  1,923 images  4,584 boxes
valid/    237 images    589 boxes
test/     269 images    642 boxes
data.yaml            nc: 1   names: ['robot']
ATTRIBUTION.md       required by CC BY 4.0 -- keep it with the data
```

Tell him **one class, already YOLO format, ready to train as-is.**

## 2. While he trains

Nothing blocks on you. The 50 matches are downloaded and their frames are extracted with the
quality filter applied, so they are waiting for his model.

## 3. When his weights arrive

Drop the `.pt` file somewhere local and run it over our frames, then fuse its output with a second
source using `ingest/collection/box_fusion.py`. That produces the calibrated confidence per box —
a box three detectors agree on outranks one that a single detector was very sure about.

---

# Robert

## What you are getting

2,429 FRC robot images, **labelled by people**, single `robot` class, already in YOLO format.
Not our model's guesses — two community datasets from Roboflow Universe, both CC BY 4.0.

## Train

```powershell
git pull
# put frc-robots-merged wherever you like, then:
yolo detect train data=<path>/frc-robots-merged/data.yaml model=yolo11s.pt epochs=100 imgsz=640
```

Send back `runs/detect/train/weights/best.pt` — about 20 MB. That is all we need from you.

## Two things about this data before you trust a number

**Ignore the source datasets' published accuracy.** WorBots reports mAP@50 of 97.6%. That number
is inflated: their splits leak. Roboflow augments each photograph into several copies and assigns
those copies to train/valid/test independently, so a flipped and blurred version of a validation
image sits in the training set. We measured it — 109 source images in both train and valid for
dark eden, 94 for WorBots.

We rebuilt the splits so every copy of a photograph lands on one side only. **Your mAP will be
lower than theirs and that is the point** — it will be a real number rather than a flattering one.
Do not tune toward 97%.

**These are 2023–2024 seasons, we run on 2026 REBUILT.** Robots look broadly alike across seasons
— bumpers, similar scale — but field graphics differ. The first thing to check after training is
whether it holds up on our REBUILT frames, not whether the validation number looks good.

## Do not

- Re-split the dataset. The splits are deliberate; reshuffling reintroduces the leak we removed.
- Add the game-piece classes back. Notes, speakers, subwoofers and displays were dropped on
  purpose — a robot detector that has learned "speaker" will label speakers.
- Commit weights or images. `data/` and `*.pt` stay out of Git.

## Then

Once the boxes look right on real footage, export to ONNX and the C++ analyzer can load it:

```powershell
yolo export model=runs/detect/train/weights/best.pt format=onnx
```

Full explanation of what training is and why each rule exists: [TRAINING.md](TRAINING.md).

---

## Why this beats the old plan

The previous route was: one small vision model guesses boxes, a human fixes all 554 of them, train
on the result. We measured what those guesses were worth — a single box size accounted for 23% of
every box drawn, and the model put "robots" on the FIRST logo. Its ceiling was low and the human
cost was hours.

Starting from 2,429 real labels skips that entirely. The model you train from them becomes the
labeller for our own footage, which is the bootstrap the project needed and could not do itself:
YOLO11 and RF-DETR both ship pretrained on COCO, which has no `robot` class, so neither could
label FRC robots until something taught one what a robot looks like.

## Still true

- Never commit `data/`, `ingest/.env`, weights, service-account JSON, or Hugging Face tokens.
- Run `.\run.ps1 check` before pushing. CI runs the same thing.
- Set `git config user.email` on your machine — the last commit landed under Justin's name.

## The two things you also own

Neither is blocked by anything above:

- **Google Sheets service account** (3.1 in [PLAN.md](PLAN.md)). Create it in Google Cloud,
  download the JSON key, share the sheet with the service account's email as **Editor**, point
  `GOOGLE_APPLICATION_CREDENTIALS` at the file. Keep the JSON outside the repo.
- **Ask about the classroom PCs** (3.2). Twenty machines with 5070 Tis. Get explicit school
  permission, and do not bulk-download YouTube video on school hardware.
