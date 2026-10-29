# Start the Vite dev server on http://localhost:5173 (proxies /api to the backend on port 8000).
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) "frontend")
npm run dev
