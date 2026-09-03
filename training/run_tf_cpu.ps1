<#
Fine-tune the portable TensorFlow/Keras robot detector on a CPU.

This script intentionally installs tensorflow-cpu and disables visible GPUs. It therefore needs
neither CUDA nor an NVIDIA GPU, and creates its own environment under training\.venv-tf-cpu.

Example:
  .\training\run_tf_cpu.ps1 -Dataset data\datasets\frc-robots-v2-coco -Output data\models\robot-v1-tf
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
# TensorFlow 2.16 publishes wheels for CPython 3.9 through 3.12 only. A bare `python -m venv`
# picks whatever is first on PATH, and on a machine with only 3.13 that produces a venv where
# `pip install tensorflow-cpu` fails with "no matching distribution" -- after the venv already
# exists, so a rerun silently reuses the broken one. Choose a supported interpreter up front and
# say so plainly when there is not one.
if (-not (Test-Path $Python)) {
    $Supported = @('3.12', '3.11', '3.10', '3.9')
    $Chosen = $null
    foreach ($v in $Supported) {
        & py -$v --version *> $null
        if ($LASTEXITCODE -eq 0) { $Chosen = $v; break }
    }
    if (-not $Chosen) {
        Write-Error ("TensorFlow 2.16 needs Python 3.9-3.12 and none is installed. " +
            "Found: " + ((& py --list) -join ' ') + ". Install 3.12 from python.org, " +
            "then rerun. Python 3.13 will NOT work.")
        exit 1
    }
    Write-Host "Creating training\.venv-tf-cpu with Python $Chosen"
    & py -$Chosen -m venv (Join-Path $PSScriptRoot '.venv-tf-cpu')
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
