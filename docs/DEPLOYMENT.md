# Deployment (free options)

KAIROS runs as a single process: FastAPI serves both the API and the built React app (`frontend/dist`).
No paid services or credentials are required. **Status: not deployed from this environment** (no hosting
account credentials were available); the container below was written for these platforms but a public URL
has not been verified. Docker is not installed in the build environment, so the Dockerfile itself has **not** been build-tested; the equivalent local production run below has been.

## Local production-style run

```powershell
cd frontend; npm run build; cd ..
.\.venv\Scripts\python.exe -m uvicorn kairos.api.app:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

## Docker

```bash
docker build -t kairos .
docker run -p 8000:8000 kairos
```

The image contains the code, the Solomon benchmark, the three shipped Amazon demo instances, the trained
travel-time model and the experiment artifacts (about 25 MB of data). The full Amazon dataset is not
included (download with `scripts/download_amazon.sh`).

## Hugging Face Spaces (free CPU tier)

1. Create a Space with SDK **Docker**.
2. Push this repository to the Space; set the Space's app port to 8000 (`app_port: 8000` in the Space README
   front matter) or set the `PORT` environment variable the Dockerfile honours.
3. The free CPU tier is enough for the interactive demo (Solomon solves take 1–5 s, Amazon instances 3–10 s).

## Render (free web service)

1. New → Web Service → connect the repository → Runtime **Docker**.
2. Render sets `PORT`; the Dockerfile's command uses it.
3. Free instances sleep when idle; the first request after a sleep takes about a minute.

## Notes

* The API keeps plans and jobs in memory; a restart clears them (experiment artifacts are on disk).
* OpenStreetMap tiles are loaded by the browser from tile.openstreetmap.org; for heavy public traffic,
  switch to a tile provider whose terms allow it.
* CC BY-NC 4.0 applies to the shipped Amazon-derived instances: do not deploy for commercial use.
