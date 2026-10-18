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

# Clone the repository
RUN git clone https://github.com/rejuce/epub2tts-chatterbox.git .

# Install the package
RUN pip install --no-cache-dir .

# Create a volume mount point for books/output
VOLUME /data

ENTRYPOINT ["epub2tts-chatterbox"]
