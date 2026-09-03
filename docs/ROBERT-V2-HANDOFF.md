# v2 training — what Robert needs

## What you're getting

`tengen-v2-yolo.tar.gz` (651 MB). Unpack it anywhere.

```
frc-robots-v2/
  data.yaml
  train/images  train/labels    2,940 images
  valid/images  valid/labels      237 images
  test/images   test/labels       269 images
  PROVENANCE.md
```

One class: `robot`. Same as v1.

There is also `tengen-v2-coco.tar.gz`, the identical data in COCO format. That one
is only for RF-DETR. **For YOLO, use the YOLO archive.**

## The command

```
yolo detect train data=<path>/frc-robots-v2/data.yaml model=yolo11s.pt epochs=150 imgsz=960 batch=8
```

Drop `batch` to 4 if the 3060 runs out of memory. `imgsz=960` matches what v1 trained at,
so the numbers are comparable — don't change it without telling us, or the comparison
against v1 stops meaning anything.

Then export:

```
yolo export model=runs/detect/train/weights/best.pt format=onnx
```

## What to send back

Just `best.onnx`, about 20 MB. Nothing else — no images, no checkpoints, no runs folder.
Also paste the final metrics line so we can compare against v1.

## What is actually in this dataset, and why it matters

Train is **1,923 human-labelled images plus 1,017 machine-labelled ones** (34% machine).
The machine labels came from running v1 over 50 real match broadcasts and keeping only
detections that two independent signals agreed on: v1's own confidence, and whether the
box persisted across neighbouring video frames.

**valid and test are human-only.** No machine label goes anywhere near them. Validating
against the model's own output measures its agreement with itself, which always looks
excellent and tells you nothing. Those two splits are the only honest yardstick we have,
so please don't merge machine data into them.

## The thing that nearly went wrong, so nobody re-introduces it

The first version of this export would have made v2 **worse** than v1.

An object detector treats every unlabelled region of an image as background. When we
first selected frames, 77% of them carried only one to three boxes — on a field with six
robots. Training on those would have taught the model, thousands of times over, that
robots are background.

Counting boxes cannot catch this, because a close-up shot legitimately contains two
robots. What catches it is doubt: if lowering the confidence bar to 0.25 reveals
candidates we were unwilling to label at 0.60, there are probably robots in that frame
we are about to call background. Frames with anything in that gap are thrown out —
**25,752 of them were.**

Everything that survived, we have no doubt about.

## Expectations

v1 was trained on 2023–24 Roboflow data. Most of what v2 adds is **our actual 2026
broadcast footage**, which v1 had never seen. So the gain to look for is on real match
video, not on the test split — the test split is still the old domain.

If v2 comes out roughly level on test but visibly tighter on real broadcasts, that is
the win we were going for.
