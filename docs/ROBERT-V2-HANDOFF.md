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
yolo detect train data=<path>/frc-robots-v2/data.yaml model=yolo11n.pt epochs=150 imgsz=960 batch=8
```

Drop `batch` to 4 if the 3060 runs out of memory.

**`yolo11n` and `imgsz=960` both matter, and both match v1 exactly.** v1's ONNX takes
`[1, 3, 960, 960]` and its checkpoint is 5.3 MB, which is yolo11n. Training v2 on a
bigger model would change the architecture and the data in the same step, and then a
better score tells us nothing about whether the new data helped — which is the entire
question this run exists to answer. Keep both the same and the comparison is clean.

If you want a stronger model afterwards, `yolo11s` on this same data is a fine second
run. Just do it as a second run.

Then export — and the size must be stated, because `yolo export` does not always inherit
it from training, and a 640 export silently mis-scales every box at inference:

```
yolo export model=runs/detect/train/weights/best.pt format=onnx imgsz=960
```

Sanity-check before sending: the exported model's input should read `[1, 3, 960, 960]`
and its output `[1, 5, N]`. If the input says 640, the export ignored the training size —
re-export with `imgsz=960`.

## What to send back

**One file: `runs/detect/train/weights/best.onnx`** (~10 MB for yolo11n).

Nothing else — no images, no `.pt` checkpoints, no `runs/` folder. Discord handles 10 MB
fine; no need for Drive.

Also paste the final metrics line (the `mAP50` / `mAP50-95` row Ultralytics prints at the
end) so it can be compared against v1.

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
