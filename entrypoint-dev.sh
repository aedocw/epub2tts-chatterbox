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

# Allow SSH access to the /data mount if it exists
# (no-op safeguard; /data is a bind mount)

echo "[entrypoint-dev] starting sshd..."
/usr/sbin/sshd

echo "[entrypoint-dev] sshd ready on :22. Container alive. SSH in to develop."

# Keep the container running
tail -f /dev/null
