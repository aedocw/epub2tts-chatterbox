# Production image for epub2tts-chatterbox.
#
# Single GPU container that serves the FastAPI web UI (with the job supervisor)
# on :8080. No SSH — this is the slim, deployable image. For the SSH-enabled
# development image see Dockerfile-dev.
#
# Build (from repo root — includes the web/ package):
#   sudo docker build -t epub2tts-chatterbox:local .
#
# Run (GPU passthrough + /data bind mount):
#   sudo docker run -d --name epub2tts-chatterbox \
#     --gpus all \
#     -e NVIDIA_VISIBLE_DEVICES=all \
#     -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
#     -e HF_HOME=/root/.cache/huggingface \
#     -v /mnt/models/epub2tts:/root/.cache/huggingface \
#     -v /mnt/dm5/_ebook:/data \
#     -p 8080:8080 \
#     epub2tts-chatterbox:local
#
# Web UI: http://<host>:8080

# Use a base image with CUDA and Python
FROM pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime

# 1. Prevent interactive prompts (like tzdata) during build
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# 2. Install system dependencies non-interactively
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    espeak-ng \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the local source (includes the web/ package).
# Build from the repo root:  docker build -t epub2tts-chatterbox:local .
COPY . /app/

# Install the package
RUN pip install --no-cache-dir .

# Create a volume mount point for books/output
VOLUME /data

# Web UI port
EXPOSE 8080

# Start the FastAPI web server (FastAPI + job supervisor) in the foreground.
ENTRYPOINT ["/opt/conda/bin/python3", "-m", "uvicorn", "epub2tts_chatterbox.web:app", "--host", "0.0.0.0", "--port", "8080"]
