#!/bin/bash
# Development entrypoint for epub2tts-chatterbox.
#
# Starts an SSH server and keeps the container alive so the agent (and you)
# can SSH in and do development interactively. Nothing is auto-run; you drive
# the server / CLI yourself over SSH.

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

echo "[entrypoint-dev] sshd ready on :22. Container alive. SSH in to develop."

# Keep the container running
tail -f /dev/null
