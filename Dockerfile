# ---------------------------------------------------------------------------
# Brightpath Crisis Relief Foundation — production image
# Flask + gunicorn, SQLite data on a mounted volume.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    BRIGHTPATH_DATA_DIR=/data

WORKDIR /app

# Minimal runtime deps (curl is used by the container healthcheck).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code.
COPY . .

# Persistent data directory (SQLite database + user uploads).
RUN mkdir -p /data/uploads/support
VOLUME ["/data"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/ >/dev/null || exit 1

CMD ["gunicorn", "--workers", "3", "--threads", "4", "--timeout", "120", \
     "--bind", "0.0.0.0:8080", "wsgi:app"]
