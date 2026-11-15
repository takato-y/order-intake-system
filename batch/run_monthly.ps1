# =============================================================
# run_monthly.ps1 : Monthly order aggregation batch (wrapper for Task Scheduler)
#   Runs batch/monthly_report.py with the project's venv and keeps a log file.
#   Written in ASCII only so that Windows PowerShell 5.1 never misreads the encoding.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy RemoteSigned -File batch\run_monthly.ps1
#   powershell -NoProfile -ExecutionPolicy RemoteSigned -File batch\run_monthly.ps1 -Month 2026-11
# Exit code: same as monthly_report.py (0 = OK, 1 = fetch failed, 2 = bad argument)
# =============================================================
param(
    [string]$Month = "",
    [string]$ApiUrl = "http://localhost:8000",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if ($OutDir -eq "") { $OutDir = Join-Path $Root "output" }
$LogDir = Join-Path $OutDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("monthly_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

# Prefer the project venv so that the scheduled task does not depend on the user's PATH.
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$PyArgs = @("-m", "batch.monthly_report", "--api-url", $ApiUrl, "--out-dir", $OutDir)
if ($Month -ne "") { $PyArgs += @("--month", $Month) }

Push-Location $Root
try {
    $env:PYTHONIOENCODING = "utf-8"
    & $Python @PyArgs *>&1 | Tee-Object -FilePath $LogFile
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
if ($code -ne 0) {
    Write-Error "monthly_report failed (exit $code). See $LogFile" -ErrorAction Continue
}
exit $code
