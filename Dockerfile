# Render's native Python runtime has no ffmpeg binary, but pydub (conversion,
# chunking) and yt-dlp (audio extraction) both shell out to it. Hence Docker.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.lock ./backend/requirements.lock
RUN pip install --no-cache-dir -r backend/requirements.lock

COPY backend ./backend
COPY scripts/prepare_reranker.py ./scripts/prepare_reranker.py
RUN python scripts/prepare_reranker.py

# Render injects $PORT.
ENV PORT=8000
# Keep job identifiers out of access logs.
CMD ["sh", "-c", "uvicorn backend.api:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
