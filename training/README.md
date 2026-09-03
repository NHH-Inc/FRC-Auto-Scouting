# /training — RF-DETR robot detector

The full explanation and every command lives in **[docs/TRAINING.md](../docs/TRAINING.md)**.
Start there; this note only covers what is in this folder.

| File | What it is |
|---|---|
| `run_rfdetr.ps1` | The one command you run. Creates `training\.venv`, installs RF-DETR + CUDA deps, trains, exports ONNX. |
| `train_rfdetr.py` | What the script calls. Do not run it directly. |
| `requirements-rfdetr.txt` | Pinned training dependencies. Separate from `ingest\.venv` on purpose. |

Requires an NVIDIA GPU. Not Justin's AMD PC, not a Mac, and never inside `ingest\.venv`.

## Portable CPU baseline

Use `run_tf_cpu.ps1` to train the same reviewed COCO data on a Ryzen CPU, with no CUDA or GPU setup. It creates its own `training/.venv-tf-cpu` environment and writes Keras artifacts:

    .\training\run_tf_cpu.ps1 -Dataset data/datasets/frc-robots-v2-coco -Output data/models/robot-v1-tf

Start with `-Resolution 320 -BatchSize 2 -Epochs 10`; train into a new output directory for a real candidate. The output is for TensorFlow evaluation until a serving adapter is added: the current C++ analyzer only accepts the RF-DETR ONNX output shape.

## AMD GPU (ROCm)

On Linux or WSL with a ROCm-supported AMD GPU, use `training/run_tf_amd_rocm.sh`. Install the
matching ROCm driver first, then run:

    ./training/run_tf_amd_rocm.sh --dataset data/datasets/frc-robots-v2-coco --output data/models/robot-v1-amd

The script checks that TensorFlow can see a GPU before training. For a specific ROCm release use
`--tensorflow-package` with AMD's compatible TensorFlow ROCm wheel URL. It has no CUDA or NVIDIA dependency.

## AMD GPU on native Windows (DirectML)

Linux is not required. With a DirectX 12-compatible AMD Radeon GPU and 64-bit Python 3.10, use:

    .\training\run_tf_amd_directml.ps1 -Dataset data/datasets/frc-robots-v2-coco -Output data/models/robot-v1-amd

This uses Microsoft's DirectML TensorFlow plugin, not ROCm or CUDA. DirectML support is paused and
is limited to the older TensorFlow 2.10 stack, so it is kept in a separate environment and is a
best-effort training option rather than the project default.

```powershell
.\training\run_rfdetr.ps1 -Dataset data\datasets\frc-robots-v2-coco -Output data\models\robot-v1
```

Everything it writes under `data\` — datasets, weights, ONNX — stays out of Git.
