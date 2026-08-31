# /training — RF-DETR robot detector

The full explanation and every command lives in **[docs/TRAINING.md](../docs/TRAINING.md)**.
Start there; this note only covers what is in this folder.

| File | What it is |
|---|---|
| `run_rfdetr.ps1` | The one command you run. Creates `training\.venv`, installs RF-DETR + CUDA deps, trains, exports ONNX. |
| `train_rfdetr.py` | What the script calls. Do not run it directly. |
| `requirements-rfdetr.txt` | Pinned training dependencies. Separate from `ingest\.venv` on purpose. |

Requires an NVIDIA GPU. Not Justin's AMD PC, not a Mac, and never inside `ingest\.venv`.

```powershell
.\training\run_rfdetr.ps1 -Dataset data\datasets\robot-v1-reviewed -Output data\models\robot-v1
```

Everything it writes under `data\` — datasets, weights, ONNX — stays out of Git.
