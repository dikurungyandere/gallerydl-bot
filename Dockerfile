# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# gallerydl-bot Dockerfile
# ---------------------------------------------------------------------------
# Single-stage build using the official Python slim image.
# Keeps the image small while including everything gallery-dl needs.
#
# Build:   docker build -t gallerydl-bot .
# Run:     docker run --env-file .env gallerydl-bot
# ---------------------------------------------------------------------------

FROM python:3.12-slim

# Don't buffer stdout/stderr and don't write .pyc files.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install Python dependencies first (better Docker layer caching).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source files.
COPY *.py ./

# The Telegram session file is stored here — mount a volume to persist it
# across container restarts (see docker-compose.yml).
VOLUME ["/app"]

# Expose the optional web UI port (only used when WEBUI=true).
EXPOSE 8080

CMD ["python", "bot.py"]
