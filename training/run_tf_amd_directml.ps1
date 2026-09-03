<#
Fine-tune the TensorFlow robot detector on an AMD GPU in native Windows using DirectML.
This route has no Linux, ROCm, CUDA, or NVIDIA dependency. It requires 64-bit Python 3.10.
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
$Venv = Join-Path $PSScriptRoot '.venv-tf-amd-directml'
$Python = Join-Path $Venv 'Scripts\python.exe'
function Resolve-TrainingPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) { return [System.IO.Path]::GetFullPath($Value) }
    return [System.IO.Path]::GetFullPath((Join-Path $Repo $Value))
}
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python Launcher (py) was not found. Install 64-bit Python 3.10, then run this command again.'
}
if (-not (Test-Path $Python)) {
    & py -3.10 -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create a Python 3.10 environment. Install 64-bit Python 3.10.' }
}
& $Python -m pip install --upgrade pip
# --pre because the DirectML plugin only ever shipped prereleases; without it pip skips them
# and reports the package as unavailable rather than saying why.
& $Python -m pip install --pre -r (Join-Path $PSScriptRoot 'requirements-tf-amd-directml.txt')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -c "import tensorflow as tf; devices = tf.config.list_physical_devices('GPU'); print('TensorFlow GPUs:', devices); assert devices, 'DirectML did not expose an AMD GPU to TensorFlow'"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python (Join-Path $PSScriptRoot 'train_tf_cpu.py') `
    --dataset (Resolve-TrainingPath $Dataset) `
    --output (Resolve-TrainingPath $Output) `
    --epochs $Epochs --batch-size $BatchSize --resolution $Resolution --learning-rate $LearningRate --device auto
exit $LASTEXITCODE
