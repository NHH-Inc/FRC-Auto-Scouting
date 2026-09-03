<#
Fine-tune the portable TensorFlow/Keras robot detector on a CPU.

This script intentionally installs tensorflow-cpu and disables visible GPUs. It therefore needs
neither CUDA nor an NVIDIA GPU, and creates its own environment under training\.venv-tf-cpu.

Example:
  .\training\run_tf_cpu.ps1 -Dataset data\datasets\robot-v1-reviewed -Output data\models\robot-v1-tf
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Dataset,
    [Parameter(Mandatory = $true)][string]$Output,
    [int]$Epochs = 50,
    [ValidateRange(1, 64)][int]$BatchSize = 2,
    [ValidateSet(320, 416, 512, 640)][int]$Resolution = 416,
    [ValidateRange(0.000001, 1.0)][double]$LearningRate = 0.0003
)

$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $PSScriptRoot '.venv-tf-cpu\Scripts\python.exe'
function Resolve-TrainingPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) { return [System.IO.Path]::GetFullPath($Value) }
    return [System.IO.Path]::GetFullPath((Join-Path $Repo $Value))
}
if (-not (Test-Path $Python)) {
    python -m venv (Join-Path $PSScriptRoot '.venv-tf-cpu')
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $PSScriptRoot 'requirements-tf-cpu.txt')
# TensorFlow reads this before import. Keep this path CPU-first even on a machine with a GPU.
$env:CUDA_VISIBLE_DEVICES = '-1'
& $Python (Join-Path $PSScriptRoot 'train_tf_cpu.py') `
    --dataset (Resolve-TrainingPath $Dataset) `
    --output (Resolve-TrainingPath $Output) `
    --epochs $Epochs --batch-size $BatchSize --resolution $Resolution --learning-rate $LearningRate --device cpu
exit $LASTEXITCODE
