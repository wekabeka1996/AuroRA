# Production-ready Dockerfile for AURORA API
FROM python:3.10-slim

# Build arg for version info
ARG VERSION=unknown
ENV AURORA_VERSION=${VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy version file and source
COPY VERSION /app/
COPY . /app

# Add version label
LABEL version=${VERSION} \
      description="AURORA v1.2 - Certified Regime-Aware Trading System"

# Expose API port
EXPOSE 8000

# Default command
CMD ["uvicorn", "api.service:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
