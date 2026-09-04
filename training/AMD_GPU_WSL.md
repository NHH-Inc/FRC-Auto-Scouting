# Training on an AMD GPU — the route that works

Verified end to end on a Radeon RX 7800 XT, 2026-09-03. This produces an ONNX file
structurally identical to the one the C++ analyzer already loads, so a model trained
here is deployable, not a science experiment.

```
Ultralytics 8.4.138  Python-3.10.12  torch-2.9.1+rocm6.4  CUDA:0 (AMD Radeon RX 7800 XT, 16177MiB)
```

The two earlier attempts (TensorFlow+DirectML, torch-directml) are dead ends and are
documented in `AMD_GPU_HANDOFF.txt`. This is the one to use.

## Why this works where the others did not

PyTorch's ROCm build presents the GPU as `cuda:0`. Ultralytics checks
`torch.cuda.is_available()`, sees True, and proceeds normally — **no patches, no forks,
no special code path.** It is the same stack that trains on an NVIDIA card, which is
also why the export is identical.

## The setup, in the order that matters

Every step below was necessary. Skipping any of them fails in a way that is hard to
diagnose.

### 1. Ubuntu 22.04, not 24.04

```powershell
wsl --install -d Ubuntu-22.04 --no-launch
```

**This is not a preference.** AMD packages the WSL runtime for jammy only — the
installer says so outright (`ROCr WSL runtime library (Ubuntu 22.04 only)`), and on
24.04 `hsa-runtime-rocr4wsl-amdgpu` simply is not in the repository. 24.04 was tried
first and got as far as the ROCm install before failing on the missing package.

Check `/dev/dxg` exists inside the distro. WSL has no `/dev/kfd`, which is why the
ordinary Linux ROCm runtime cannot work here and the WSL-specific one is required.

### 2. ROCm 6.4.4, not 7.x

```bash
wget https://repo.radeon.com/amdgpu-install/6.4.4/ubuntu/jammy/amdgpu-install_6.4.60404-1_all.deb
apt install ./amdgpu-install_6.4.60404-1_all.deb
amdgpu-install -y --usecase=wsl,rocm --no-dkms
```

An awkward version squeeze, worth understanding before someone "helpfully" upgrades:

* ROCm **7.0** is where AMD officially lists gfx1101 (the 7800 XT) as supported, but
  7.0 and later **dropped** `hsa-runtime-rocr4wsl-amdgpu`. The `wsl` usecase is gone
  from the 7.2.4 installer entirely and errors out in 7.0.2.
* ROCm **6.4.4** still ships the WSL runtime, and gfx1101 works on it in practice —
  `rocminfo` reports the card by name with no `HSA_OVERRIDE_GFX_VERSION` needed.

`--no-dkms` matters: WSL uses the Windows driver through `/dev/dxg`, so there is no
kernel module to build and asking for one fails.

Confirm with `rocminfo` — it should name `gfx1101` and `AMD Radeon RX 7800 XT`.
`rocm-smi` reports `Driver not initialized (amdgpu not found in modules)` and that is
expected and harmless in WSL.

### 3. PyTorch for ROCm, then swap the HSA runtime

```bash
python3 -m venv /root/tengen && . /root/tengen/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.4

loc=$(pip show torch | awk -F': ' '/^Location/{print $2}')
cd "$loc/torch/lib"
rm -f libhsa-runtime64.so*
cp /opt/rocm/lib/libhsa-runtime64.so.1 libhsa-runtime64.so
```

**The swap is the step everyone misses.** The PyTorch wheel bundles the ordinary Linux
HSA runtime, which talks to `/dev/kfd` and finds nothing. Replacing it with the WSL
runtime from `/opt/rocm` is what makes `torch.cuda.is_available()` return True.

### 4. Ultralytics

```bash
apt install -y libgl1 libglib2.0-0     # opencv needs these
pip install ultralytics onnx onnxruntime
```

## Training

Keep the dataset on the **ext4 side**, not `/mnt/c`. The Windows mount is 9p and slow
for thousands of small files; copying the dataset in first is much faster than reading
it across the boundary every epoch.

```bash
yolo detect train data=/root/data/frc-robots-v2/data.yaml model=yolo11n.pt \
  epochs=150 imgsz=960 batch=8 device=0
yolo export model=runs/detect/train/weights/best.pt format=onnx imgsz=960
```

Verified the export matches v1 exactly:

| | input | output | size |
|---|---|---|---|
| v1 (NVIDIA-trained) | `images [1,3,960,960]` | `output0 [1,5,18900]` | 10.3 MB |
| this (AMD-trained)  | `images [1,3,960,960]` | `output0 [1,5,18900]` | 10.3 MB |

## Cost

About **35 GB** — ROCm is 19 GB and the PyTorch ROCm venv another 16 GB, since those
wheels bundle their own ROCm libraries. Plus the Ubuntu base. Worth knowing before
starting; `wsl --unregister Ubuntu-22.04` reclaims all of it.

## Harmless noise

`Warning: Resource leak detected by SharedSignalPool, N Signals leaked.` appears at the
end of a run. It is a ROCm cleanup warning, not a training problem.
