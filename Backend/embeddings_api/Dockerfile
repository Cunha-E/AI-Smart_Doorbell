# syntax=docker/dockerfile:1

# Comments are provided throughout this file to help you get started.
# If you need more help, visit the Dockerfile reference guide at
# https://docs.docker.com/go/dockerfile-reference/

# Want to help us make this template better? Share your feedback here: https://forms.gle/ybq9Krt8jtBL3iCk7

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS base

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by OpenCV (used by DeepFace)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create a non-privileged user that the app will run under.
# See https://docs.docker.com/go/dockerfile-user-best-practices/
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/home/appuser" \
    --shell "/sbin/nologin" \
    --uid "${UID}" \
    appuser

# Download dependencies as a separate step to take advantage of Docker's caching.
# Leverage a cache mount to /root/.cache/pip to speed up subsequent builds.
# Leverage a bind mount to requirements.txt to avoid having to copy them into
# into this layer.
#RUN --mount=type=cache,target=/root/.cache/pip \
#    --mount=type=bind,source=requirements.txt,target=requirements.txt \
#    python -m pip install -r requirements.txt
# Install Python dependencies
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

# Switch to the non-privileged user to run the application.
USER appuser

# Copy the source code into the container.
COPY . .

# Expose the port that the application listens on.
EXPOSE 8085

# Run the application.
CMD ["gunicorn","source.app:flask_app","--bind=0.0.0.0:8085","--workers=1","--threads=4","--timeout=120"]
