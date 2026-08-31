# Train the FRC robot detector — exact instructions

This trains the one-class **robot** detector used by the C++ analysis program. It does **not**
train team-number recognition, shots, reloads, or live scouting.

**Owner:** Robert, on his Windows desktop with the RTX 3060 12 GB NVIDIA GPU.

**Do not use:** a Mac, Justin's AMD Windows PC, the shared Supabase database, Google Sheets, or
`ingest\.venv` for training.

---

## 0. What has to exist before training can work

You need reviewed full-frame FRC robot boxes from **at least three different matches**. A single
match is not enough because frames from one match must stay together in either train, validation,
or test—otherwise near-identical frames leak into validation and the accuracy number lies.

Each training image has exactly one class:

```text
robot
```

Do not make a class per FRC team. Team identification is a separate future classifier.

---

## 1. Get the newest project code

Open PowerShell in the repository root:

```powershell
cd "C:\Coding Stuff\Robotics\FRC-Auto-Scouting"
git pull
.\run.ps1 check
```

`check` must finish with **All checks passed** before changing anything.

---

## 2. Make collections from three or more match recordings

Use actual downloaded MP4 match segments in `data\segments\`. Repeat the command below once per
different match. Replace every `<...>` placeholder with real values.

```powershell
# in: C:\Coding Stuff\Robotics\FRC-Auto-Scouting
.\ingest\.venv\Scripts\python.exe -m ingest.collection.cli extract `
  --segment data\segments\<downloaded-match-file>.mp4 `
  --match-id <tba-match-key-like-2026casf_qm42> `
  --video-id <11-character-youtube-id> `
  --source-url "https://www.youtube.com/watch?v=<11-character-youtube-id>" `
  --start-offset 0 `
  --config configs\data_collection.example.yaml
```

The command prints a collection directory like:

```text
data\collections\2026casf_qm42-...
```

Copy that path somewhere. You need all of them later.

---

## 3. Create initial robot-box proposals

### Option A — existing three-model Ollama ensemble

Run this for every collection. It creates proposals from the two Qwen vision models and Gemma;
none are training labels yet.

```powershell
# in: repository root
.\ingest\.venv\Scripts\python.exe -m ingest.collection.cli auto-label `
  --collection data\collections\<collection-id> `
  --config configs\data_collection.example.yaml
```

### Option B — optional SAM 3.1 proposals

Only do this after SAM 3.1 is installed in Robert's separate CUDA environment. It writes a
separate proposal file and does not change the Ollama consensus.

```powershell
# in: repository root
C:\FRC-SAM3\.venv\Scripts\python.exe -m ingest.collection.cli sam3-propose `
  --collection data\collections\<collection-id> `
  --limit 10
```

First inspect ten frames. If SAM really finds FRC robots cleanly, rerun without `--limit 10`:

```powershell
C:\FRC-SAM3\.venv\Scripts\python.exe -m ingest.collection.cli sam3-propose `
  --collection data\collections\<collection-id>
```

SAM is optional. Do not wait on it if it performs poorly; reviewed robot boxes are the goal.
See [docs/SAM3.md](docs/SAM3.md) for its separate installation.

---

## 4. Create a COCO upload folder

For the **temporary test baseline**, materialize the Ollama consensus into COCO format. Replace
the three collection paths with your actual paths:

```powershell
# in: repository root
.\ingest\.venv\Scripts\python.exe -m ingest.collection.cli export-coco `
  --collection data\collections\<match-one> data\collections\<match-two> data\collections\<match-three> `
  --config configs\data_collection.example.yaml `
  --output data\datasets\robot-v1 `
  --allow-unreviewed
```

`--allow-unreviewed` is allowed only for this first experiment. It makes the quality compromise
visible; it does not make model proposals correct.

This creates:

```text
data\datasets\robot-v1\train\_annotations.coco.json
data\datasets\robot-v1\valid\_annotations.coco.json
data\datasets\robot-v1\test\_annotations.coco.json
```

---

## 5. Review labels in Roboflow — recommended path

1. Create a **private Object Detection** project named `FRC Robot Boxes`.
2. Create one class only: `robot`.
3. Upload the three folders inside `data\datasets\robot-v1`: `train`, `valid`, and `test`.
   Choose **COCO JSON** if Roboflow asks for the format. Preserve the split names.
4. For every frame:
   - Delete boxes around people, field elements, the score overlay, or images on screens.
   - Add every missed visible robot.
   - Keep one tight box around the full physical robot, including its bumper when visible.
   - Exclude replay close-ups and unusable camera-cut frames instead of labelling them badly.
5. Export/download the reviewed dataset in **COCO JSON** format to a new local folder, for example:

```text
data\datasets\robot-v1-reviewed
```

Before training, verify this exists:

```text
data\datasets\robot-v1-reviewed\train\_annotations.coco.json
data\datasets\robot-v1-reviewed\valid\_annotations.coco.json
```

The reviewed folder is the one to train from. Do not overwrite it with a new unreviewed export.

---

## 6. Train RF-DETR

Run this on Robert's RTX 3060 computer from the repository root:

```powershell
.\training\run_rfdetr.ps1 `
  -Dataset data\datasets\robot-v1-reviewed `
  -Output data\models\robot-v1
```

The script automatically creates `training\.venv`, installs RF-DETR and its CUDA Python
dependencies, trains **RF-DETR Small** for 100 epochs at 640 px, chooses a safe batch size for
the 12 GB card, tests the dataset, and exports ONNX.

It uses safe default augmentation:

- horizontal flips;
- mild brightness/contrast variation;
- RF-DETR's normal resize/scale jitter.

It does **not** vertically flip, heavily rotate, or strongly warp frames because those do not look
like an FRC broadcast.

For a short installation-only test, use a different output folder:

```powershell
.\training\run_rfdetr.ps1 `
  -Dataset data\datasets\robot-v1-reviewed `
  -Output data\models\robot-smoke `
  -Epochs 3
```

Do not treat the three-epoch model as your final model.

---

## 7. Confirm the model exported

After a successful real run, these must exist:

```text
data\models\robot-v1\onnx\inference_model.onnx
data\models\robot-v1\training-config.json
```

`training-config.json` records model size, epochs, resolution, batch setting, and augmentation.
The ONNX file is model data: **do not commit it to Git**.

---

## 8. Enable the model in the C++ analyzer

Create the ignored local configuration file:

```powershell
# in: repository root
Copy-Item analysis\config\detector.example.json analysis\config\detector.local.json
```

Open `analysis\config\detector.local.json`. If the model is at the standard location above, do
not change `model_path`. It should be:

```json
"model_path": "../../data/models/robot-v1/onnx/inference_model.onnx"
```

Start the complete app with the model enabled:

```powershell
$env:FRC_DETECTOR_CONFIG = (Resolve-Path "analysis\config\detector.local.json").Path
.\run.ps1 full
```

Queue one real, previously unseen match video. The analysis view should report a configured
detector and nonzero tracks. Check the overlay: boxes should stay on robots and gaps should appear
at broadcast cuts rather than drawing through them.

---

## 9. If something fails

| Problem | Fix |
|---|---|
| `CUDA was not detected` | Run training on Robert's NVIDIA desktop; update the NVIDIA driver if needed. |
| Missing `train/_annotations.coco.json` or `valid/_annotations.coco.json` | Re-export/download the COCO dataset. A single match is not enough. |
| Roboflow labels look wrong | Fix them in Roboflow, export a new reviewed folder, and train into a new `data\models\...` folder. |
| No tracks after training | Confirm `FRC_DETECTOR_CONFIG` is set in the same PowerShell window that runs `run.ps1 full`, and verify the ONNX path exists. |
| Boxes are wrong | Keep raw outputs/corrections, collect more reviewed matches, and train a new version. Never overwrite the old model or raw event output. |

---

## Never commit these files

```text
data\                       # videos, frames, datasets, model weights
analysis\config\detector.local.json
ingest\.env                 # Supabase and API secrets
training\.venv\
C:\FRC-SAM3\.venv\
SAM checkpoints or Hugging Face tokens
```

When finished, run:

```powershell
.\run.ps1 check
git status
```

Only commit source code and documentation. The dataset, video, model, and secrets stay local.
