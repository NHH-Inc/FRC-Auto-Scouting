#!/usr/bin/env bash
# Fine-tune the TensorFlow robot detector on a supported AMD GPU through ROCm.
# Run this in Linux or WSL after installing ROCm for the host GPU. It intentionally has no CUDA
# or NVIDIA dependency. The default package name can be overridden with a compatible AMD wheel URL.
#
# Example:
#   ./training/run_tf_amd_rocm.sh --dataset data/datasets/frc-robots-v2-coco --output data/models/robot-v1-amd
#   ./training/run_tf_amd_rocm.sh --tensorflow-package https://repo.radeon.com/.../tensorflow_rocm-...whl ...
set -euo pipefail

dataset=""
output=""
epochs=50
batch_size=4
resolution=416
learning_rate=0.0003
tensorflow_package="${TF_ROCM_PACKAGE:-tensorflow-rocm}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataset) dataset="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    --epochs) epochs="$2"; shift 2 ;;
    --batch-size) batch_size="$2"; shift 2 ;;
    --resolution) resolution="$2"; shift 2 ;;
    --learning-rate) learning_rate="$2"; shift 2 ;;
    --tensorflow-package) tensorflow_package="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$dataset" || -z "$output" ]]; then
  echo "Usage: $0 --dataset DATASET --output OUTPUT [--tensorflow-package WHEEL_OR_PACKAGE]" >&2
  exit 2
fi
if ! command -v rocminfo >/dev/null 2>&1; then
  echo "ROCm was not found (rocminfo is unavailable). Install ROCm for this AMD GPU before training." >&2
  exit 1
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$repo/training/.venv-tf-amd-rocm"
python3 -m venv "$venv"
"$venv/bin/python" -m pip install --upgrade pip
"$venv/bin/python" -m pip install "$tensorflow_package"
"$venv/bin/python" -m pip install -r "$repo/training/requirements-tf-amd-rocm.txt"
"$venv/bin/python" - <<'PY'
import tensorflow as tf
gpus = tf.config.list_physical_devices("GPU")
if not gpus:
    raise SystemExit("TensorFlow cannot see an AMD ROCm GPU. Check the ROCm and TensorFlow wheel compatibility.")
print("TensorFlow GPUs:", gpus)
PY
"$venv/bin/python" "$repo/training/train_tf_cpu.py" \
  --dataset "$dataset" --output "$output" --epochs "$epochs" --batch-size "$batch_size" \
  --resolution "$resolution" --learning-rate "$learning_rate" --device auto
