# ---- Stage 1: Build frontend ----
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python app ----
FROM python:3.11-slim

# Install system dependencies (ffmpeg excluded — Debian's ffmpeg package
# has a broken libavcodec61 that fails to unpack on fresh Docker builds)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp (latest version)
RUN pip install --no-cache-dir yt-dlp

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
# Use --no-compile to reduce memory during install (Railway has tight build limits)
COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile -r requirements.txt

# Copy application code
COPY . .

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist /app/frontend/dist

# Create necessary directories
RUN mkdir -p /app/data_volume/campaigns/active \
    /app/data_volume/campaigns/completed \
    /app/data_volume/cache \
    /app/data_volume/config \
    /app/data_volume/internal_cache

# Expose port (Railway will override with PORT env var)
EXPOSE 5055

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5055/health')"

# Run the Flask app with gunicorn (production WSGI server)
# 4 workers, 120s timeout for long scraping operations, bind to PORT env var
CMD gunicorn --workers 4 --timeout 120 --bind 0.0.0.0:${PORT:-8080} "campaign_manager:create_app()"
