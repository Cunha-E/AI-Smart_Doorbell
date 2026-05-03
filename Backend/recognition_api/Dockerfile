# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# System deps for OpenCV (DeepFace)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ARG UID=10001
RUN adduser --disabled-password --gecos "" --home "/home/appuser" --shell "/sbin/nologin" --uid "${UID}" appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install curl for direct model download
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Pre-download DeepFace model weights during build to avoid
# corrupted downloads at runtime on Cloud Run's ephemeral filesystem
# (The upstream GitHub URL is dead, so we host weights in our GCS bucket)
RUN mkdir -p /home/appuser/.deepface/weights && \
    curl -fSL -o /home/appuser/.deepface/weights/arcface_weights.h5 \
      https://storage.googleapis.com/ai-doorbell-c6bb9_cloudbuild/deepface_weights/arcface_weights.h5 && \
    curl -fSL -o /home/appuser/.deepface/weights/retinaface.h5 \
      https://storage.googleapis.com/ai-doorbell-c6bb9_cloudbuild/deepface_weights/retinaface.h5 && \
    ls -lh /home/appuser/.deepface/weights/ && \
    chown -R appuser:appuser /home/appuser/.deepface

USER appuser
COPY . .
EXPOSE 8089
CMD ["gunicorn","source.app:flask_app","--bind=0.0.0.0:8089","--workers=1","--threads=4","--timeout=120"]
