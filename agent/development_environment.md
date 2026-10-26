# Development Environment — epub2tts-chatterbox

> Quick-reference for connecting to and working inside the dev container.

## SSH Connection

```bash
ssh -i /workspace/repos/keys/epub2tts/github-epub2tts \
    -o StrictHostKeyChecking=accept-new \
    -p 2222 root@192.168.0.3
```

| Field | Value |
|-------|-------|
| Host | `192.168.0.3` |
| Port | `2222` |
| User | `root` |
| Private key | `/workspace/repos/keys/epub2tts/github-epub2tts` |
| Auth | Public key (`.pub` auto-registered by entrypoint into `authorized_keys`) |

> **Shortcut for every SSH command:** prefix with the `ssh -i … -p 2222 root@192.168.0.3` above.
> No password needed.

## Container Overview

| Item | Detail |
|------|--------|
| Image | `epub2tts-chatterbox-dev` (built from `Dockerfile-dev`) |
| Container name | `epub2tts-chatterbox-dev` |
| GPU | **GTX 1080, 8 GB** (GPU index 1 on host) |
| Base | `pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime` (actually ships **Python 3.10.13, torch 2.6.0+cu124**) |
| Compose file | `docker-compose.dev.yml` (in repo root) |

## Key Paths (inside container)

| Path | Purpose |
|------|---------|
| `/app` | Git checkout of the repo (cloned at build time). Currently on `main`. For dev: `git fetch origin && git checkout dev && pip install -e .` |
| `/data` | Bind mount → host `/mnt/dm5/_ebook`. Contains `books/`, `samples/`, `jobs/` subdirs (created by entrypoint) |
| `/root/.cache/huggingface` | Chatterbox model cache (bind-mounted, persistent) |
| `/root/.ssh` | Read-only mount of `/workspace/repos/keys/epub2tts` (git deploy key + SSH keypair) |
| `/opt/conda/bin/python3` | **Python 3.10.13** — always use this absolute path |
| `/opt/conda/bin/pip` | pip for the conda env |

## Important Gotchas

1. **`python` / `python3` are NOT on the default non-login PATH.**
   Always use `/opt/conda/bin/python3` (and `/opt/conda/bin/pip`).
   Or prefix with `source /opt/conda/etc/profile.d/conda.sh &&`.

2. **No `which` command.** Use `command -v <cmd>` instead.

3. **Git pager:** Set `GIT_PAGER=cat` or use `git --no-pager` to avoid interactive pager hangs in non-TTY sessions.

4. **The container keeps alive via `tail -f /dev/null`** in `entrypoint-dev.sh`. Nothing auto-runs. You drive everything over SSH.

5. **CWD-dependent output:** The CLI tool writes `partN.flac`, `pgraphsN.flac`, etc. to the **current working directory**. Always `cd` into the job dir before running TTS.

6. **Model cache:** Chatterbox model (~GBs) is cached at `/root/.cache/huggingface`. First TTS run will download if missing.

## Git / Push

- Remote: `git@github.com:rejuce/epub2tts-chatterbox.git` (SSH)
- Deploy key for push: `/workspace/repos/keys/epub2tts/github-epub2tts`
  - Also copied to `~/.ssh/id_github_epub2tts` in the agent environment
- Push command:
  ```bash
  GIT_SSH_COMMAND="ssh -i ~/.ssh/id_github_epub2tts -o StrictHostKeyChecking=accept-new" \
    git push origin dev
  ```
- Working branch: `dev`

## System Tools Available

| Tool | Path |
|------|------|
| ffmpeg | `/usr/bin/ffmpeg` |
| espeak-ng | `/usr/bin/espeak-ng` |
| git | `/usr/bin/git` |
| nvidia-smi | `/usr/bin/nvidia-smi` |

## Docker Build / Run (manual, on host)

```bash
# Build (from repo root, on branch dev)
sudo docker build -f Dockerfile-dev -t epub2tts-chatterbox-dev .

# Run (or use docker-compose.dev.yml via Portainer)
sudo docker run -d --name epub2tts-chatterbox-dev \
  --gpus all \
  -e NVIDIA_VISIBLE_DEVICES=1 \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  -e HF_HOME=/root/.cache/huggingface \
  -v /mnt/models/epub2tts:/root/.cache/huggingface \
  -v /mnt/dm5/_ebook:/data \
  -v /workspace/repos/keys/epub2tts:/root/.ssh:ro \
  -p 2222:22 \
  epub2tts-chatterbox-dev
```

## Typical Dev Session Flow

```bash
# 1. SSH in
ssh -i /workspace/repos/keys/epub2tts/github-epub2tts -p 2222 root@192.168.0.3

# 2. Get to dev branch in /app
cd /app
git fetch origin
git checkout dev
pip install -e .

# 3. Work (edit files, run server, test, etc.)
/opt/conda/bin/python3 -m uvicorn epub2tts_chatterbox.web:app --host 0.0.0.0 --port 8080

# 4. Commit + push (from the agent side, or inside container with the key)
git add -A && git commit -m "..."
GIT_SSH_COMMAND="ssh -i /root/.ssh/github-epub2tts -o StrictHostKeyChecking=accept-new" \
  git push origin dev
```
