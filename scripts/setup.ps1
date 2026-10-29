# KAIROS one-time setup (Windows PowerShell). Requires Python 3.11 (3.10-3.13 work) and Node 20+.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$py = $null
foreach ($cand in @("py -3.11", "python3.11", "python")) {
  try {
    $v = & ([scriptblock]::Create("$cand --version")) 2>$null
    if ($v -match "Python 3\.(1[0-3])") { $py = $cand; break }
  } catch {}
}
if (-not $py) { throw "Python 3.10-3.13 not found. Install Python 3.11 from python.org." }
Write-Host "Using $py"

if (-not (Test-Path .venv)) { & ([scriptblock]::Create("$py -m venv .venv")) }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

Push-Location frontend
npm install
npm run build
Pop-Location
Write-Host "Setup complete. Start with scripts\run_backend.ps1 and scripts\run_frontend.ps1 (or open http://127.0.0.1:8000 after run_backend for the built UI)."
