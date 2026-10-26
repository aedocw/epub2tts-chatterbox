#!/bin/bash
# Development entrypoint for epub2tts-chatterbox.
#
# Starts sshd + the FastAPI web server (with job supervisor) automatically.
# Keeps the container alive so the agent (and you) can SSH in to develop.
# The web server auto-starts on :8080 and survives container restarts.

set -euo pipefail

# Ensure runtime dirs exist
mkdir -p /run/sshd
mkdir -p /data /data/books /data/samples /data/jobs

# SSH: wire the mounted public key into a writable authorized_keys.
# The key dir is bind-mounted READ-ONLY at /root/.ssh, so we cannot write
# authorized_keys inside it. Instead we copy the public key out to
# /etc/ssh/authorized_keys, which sshd is configured to read (see Dockerfile).
if [ -f /root/.ssh/github-epub2tts.pub ]; then
    cp /root/.ssh/github-epub2tts.pub /etc/ssh/authorized_keys
    chmod 600 /etc/ssh/authorized_keys
    echo "[entrypoint-dev] authorized_keys set from mounted public key."
else
    echo "[entrypoint-dev] WARNING: /root/.ssh/github-epub2tts.pub not found; key auth disabled."
fi

echo "[entrypoint-dev] starting sshd..."
/usr/sbin/sshd

echo "[entrypoint-dev] sshd ready on :22."

# Auto-start the web server (FastAPI + supervisor) so it survives container restarts.
# Logs go to /var/log/uvicorn.log. You can still SSH in to manage it:
#   tail -f /var/log/uvicorn.log
#   kill $(cat /var/run/uvicorn.pid)   # stop
#   nohup /opt/conda/bin/python3 -m uvicorn epub2tts_chatterbox.web:app \
#     --host 0.0.0.0 --port 8080 > /var/log/uvicorn.log 2>&1 &   # restart

echo "[entrypoint-dev] starting web server on :8080..."
cd /app
nohup /opt/conda/bin/python3 -m uvicorn epub2tts_chatterbox.web:app \
  --host 0.0.0.0 --port 8080 > /var/log/uvicorn.log 2>&1 &
UVICORN_PID=$!
echo $UVICORN_PID > /var/run/uvicorn.pid

# Give it a few seconds to come up, then verify
sleep 5
if kill -0 $UVICORN_PID 2>/dev/null; then
    echo "[entrypoint-dev] web server running (pid $UVICORN_PID) on :8080"
else
    echo "[entrypoint-dev] WARNING: web server failed to start. Check /var/log/uvicorn.log"
fi

echo "[entrypoint-dev] ready. SSH in to develop."

# Keep the container running
tail -f /dev/null
