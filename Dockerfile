# Use a base image with CUDA and Python
FROM pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Clone the actual source
RUN git clone https://github.com/rejuce/epub2tts-chatterbox.git .

# Install the package
RUN pip install --no-cache-dir .

# Create a volume mount point for books/output
VOLUME /data

# Set the command (adjust based on how you want to run it)
ENTRYPOINT ["epub2tts"]
