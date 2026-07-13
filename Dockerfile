# Render's native Python runtime has no ffmpeg binary, but pydub (conversion,
# chunking) and yt-dlp (audio extraction) both shell out to it. Hence Docker.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend

# Render injects $PORT.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn backend.api:app --host 0.0.0.0 --port ${PORT}"]
