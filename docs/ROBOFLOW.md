# Roboflow review handoff

This is the one task that cannot be completed by a script: somebody must look at robot boxes and
decide whether they are right. Robert owns this step. It does not require Supabase, Google Sheets
or putting any secret in this repository.

## Before you start

Collect several **different matches** first. Frames from a match always share one split so nearby
frames cannot leak from training into validation. One match is not a trainable dataset.

For each clipped segment, run the existing collection commands from the repository root:

```powershell
.\ingest\.venv\Scripts\python -m ingest.collection.cli extract --help
.\ingest\.venv\Scripts\python -m ingest.collection.cli auto-label --help
```

Then combine the collections into a disposable COCO upload/training directory. Use
`--allow-unreviewed` only for the temporary first pass; it deliberately records that the labels
are model proposals, not ground truth.

```powershell
.\ingest\.venv\Scripts\python -m ingest.collection.cli export-coco `
  --collection data\collections\<match-one> data\collections\<match-two> data\collections\<match-three> `
  --config configs\data_collection.example.yaml `
  --output data\datasets\robot-v1 `
  --allow-unreviewed
```

## In Roboflow

1. Create a private object-detection project named something obvious, such as `FRC Robot Boxes`.
2. Create the single class `robot`. Do not add team numbers, goals or match events here.
3. Upload the three COCO split folders from `data\datasets\robot-v1` while preserving their
   `train`, `valid` and `test` split names. If Roboflow's upload page asks for a format, choose
   COCO JSON.
4. Review the proposed boxes: remove boxes on field elements/people, add missed robots, and make
   sure each remaining box tightly covers one robot. Mark difficult close-ups and camera cuts as
   excluded rather than teaching the detector bad examples.
5. Export the reviewed version in COCO format if you train from Roboflow. Or download it to a
   new local folder and give that folder to `training\run_rfdetr.ps1`.

## Definition of done

Robert sends the team one thing: a local COCO dataset folder with non-empty `train` and `valid`
folders, each containing `_annotations.coco.json`. Then the local training command is:

```powershell
.\training\run_rfdetr.ps1 -Dataset <reviewed-coco-folder> -Output data\models\robot-v1
```

The resulting `onnx\inference_model.onnx` is local model data, not source code. Keep it out of
Git. Point the ignored `analysis\config\detector.local.json` at it and set
`FRC_DETECTOR_CONFIG` before launching a real job.
