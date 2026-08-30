# RF-DETR robot detector

This folder is for Robert's NVIDIA/CUDA machine. Do not run it in `ingest\.venv`, and do not try
to train on Justin's AMD Windows machine.

## 1. Produce labels

Run the existing `extract` and `auto-label` collection commands on a clipped match. Review the
proposals in Roboflow when its project is available. The collection manifest remains the source
of truth; images in a training dataset are disposable materializations.

For the explicitly temporary v1 baseline only, turn consensus proposals from **several different
matches** into RF-DETR's required COCO layout. A match is assigned to one split as a group, so a
single-match collection cannot provide an honest train/validation dataset:

```powershell
.\ingest\.venv\Scripts\python -m ingest.collection.cli export-coco `
  --collection data\collections\<match-one> data\collections\<match-two> data\collections\<match-three> `
  --config configs\data_collection.example.yaml `
  --output data\datasets\robot-v1 `
  --allow-unreviewed
```

Do **not** omit `--allow-unreviewed` unless the label file really has reviewed statuses. Its
presence makes the temporary quality compromise visible in every training command.

## 2. Train and export

```powershell
.\training\run_rfdetr.ps1 -Dataset data\datasets\robot-v1 -Output data\models\robot-v1
```

It uses RF-DETR Small, `640px`, `100` epochs, and `batch-size auto`; RF-DETR picks a safe batch
for Robert's 12 GB card. The exported file is
`data\models\robot-v1\onnx\inference_model.onnx`.

## 3. Enable C++ inference

Copy `analysis\config\detector.example.json` to a local file that is not committed, update its
`model_path` to the exported ONNX file, then set this before running the ingest service:

```powershell
$env:FRC_DETECTOR_CONFIG = 'analysis\config\detector.local.json'
.\run.ps1 full
```

The C++ backend reads RF-DETR's named `dets` and `labels` outputs, retains only class `robot`,
and emits normalized boxes with explicit gaps at detected broadcast cuts. It does **not** yet do
bumper OCR, team identification, field homography, or action events.
