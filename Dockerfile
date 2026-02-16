FROM pytorch/pytorch:2.9.1-cuda12.6-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg espeak-ng git ca-certificates build-essential \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Make torch/torchvision/torchaudio consistent.
# Use the cu124 wheel index to keep everything aligned.
RUN python -m pip install -U pip setuptools wheel \
 && python -m pip uninstall -y torch torchvision torchaudio || true \
 && python -m pip install --index-url https://download.pytorch.org/whl/cu124 \
      torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
 && pip install . \
 && python -m pip install --index-url https://download.pytorch.org/whl/cu124 \
      torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0

WORKDIR /work
ENTRYPOINT ["epub2tts-chatterbox"]
CMD ["-h"]
