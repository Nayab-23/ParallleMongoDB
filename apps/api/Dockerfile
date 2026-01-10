# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEPLOYMENT_MODE=self-hosted

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (cached layer)
# Use the docker-specific lockfile so all prod deps (incl. SQLAlchemy) are installed.
COPY requirements-docker.txt .
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements-docker.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start minimal hackathon backend
CMD ["sh", "-c", "uvicorn hack_main:app --host 0.0.0.0 --port 8000 --workers 2"]
