<#
Runs on Robert's Windows NVIDIA machine only. It creates a separate training environment so
PyTorch/RF-DETR never contaminates the ingest service's runtime environment.

Example:
  .\training\run_rfdetr.ps1 -Dataset data\datasets\robot-v1 -Output data\models\robot-v1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Dataset,
    [Parameter(Mandatory = $true)][string]$Output,
    [ValidateSet('nano', 'small', 'medium')][string]$Variant = 'small',
    [int]$Epochs = 100,
    [string]$BatchSize = 'auto',
    [int]$Resolution = 640,
    [ValidateSet('conservative', 'none')][string]$Augmentation = 'conservative'
)

$Repo = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
function Resolve-TrainingPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) { return [System.IO.Path]::GetFullPath($Value) }
    return [System.IO.Path]::GetFullPath((Join-Path $Repo $Value))
}
if (-not (Test-Path $Python)) {
    python -m venv (Join-Path $PSScriptRoot '.venv')
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $PSScriptRoot 'requirements-rfdetr.txt')
& $Python (Join-Path $PSScriptRoot 'train_rfdetr.py') `
    --dataset (Resolve-TrainingPath $Dataset) `
    --output (Resolve-TrainingPath $Output) `
    --variant $Variant --epochs $Epochs --batch-size $BatchSize --resolution $Resolution `
    --augmentation $Augmentation
exit $LASTEXITCODE
