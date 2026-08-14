param()
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$target = Join-Path $repo 'controllers\base_controller.py'
$baseline = Join-Path $repo 'artifacts\recovery_spinner_diagnosis_BASELINE.py'
if (-not (Test-Path $baseline)) { throw "Missing baseline: $baseline" }
Copy-Item $baseline $target -Force
$actual=(Get-FileHash $target -Algorithm SHA256).Hash
$expected=(Get-FileHash $baseline -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw "Rollback hash mismatch: $actual != $expected" }
Write-Output "ROLLBACK_OK $actual"
