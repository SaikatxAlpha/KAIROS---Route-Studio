# Start the KAIROS API on http://127.0.0.1:8000 (also serves frontend/dist when built).
Set-Location (Split-Path $PSScriptRoot -Parent)
.\.venv\Scripts\python.exe -m uvicorn kairos.api.app:app --host 127.0.0.1 --port 8000
