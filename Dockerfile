# Single-container deployment: FastAPI serves the API and the built React app.
# docker build -t kairos . && docker run -p 8000:8000 kairos
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY kairos/ kairos/
COPY data/benchmarks/ data/benchmarks/
COPY data/demo/ data/demo/
COPY artifacts/ artifacts/
COPY --from=web /app/frontend/dist frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "uvicorn kairos.api.app:app --host 0.0.0.0 --port ${PORT}"]
