# Progress Log

## 2026-07-17

### Phase 1 — Repo setup & investigation
- [x] Cloned `https://github.com/rejuce/epub2tts-chatterbox.git` into `/workspace/repos/epub2tts-chatterbox`
- [x] Created `/workspace/repos/epub2tts-chatterbox/agent/`
- [x] Read README.md, main script, `epub_export.py`, requirements.txt, setup.py, Dockerfile, `__init__.py`
- [x] Created `agent/outline.md` — full repo reference (CLI usage, text format, output, pipeline internals, reusable library, gotchas)

### Phase 2 — Architecture (design only, NO implementation)
- [x] Created `agent/architecture.md` — Docker Composeable stack design
- [x] Added cross-reference in `outline.md` → `architecture.md`

### Phase 3 — Simplification (feedback: too many moving parts)
- [x] **Removed Postgres** → `state.json` per job dir is the database
- [x] **Removed Redis / queue service** → worker polls the jobs directory (one GPU = one job at a time)
- [x] Result: **2 services (web + worker) + 1 shared volume**, files as state
- [x] Rewrote `architecture.md` around this simpler model:
  - [x] Job state machine lives in `state.json`
  - [x] Worker = simple directory poller (no broker)
  - [x] Progress via `state.json` (+ optional hot `progress.json`), SSE + polling
  - [x] Crash/restart resume via tool's built-in `partN.flac` checkpoints
  - [x] eBook browsing, FastAPI endpoints, compose sketch, reliability table all retained

### Phase 4 — Single-container dev architecture + working branch `container`
- [x] Architecture decision: collapse to **one GPU container**, agent develops over **SSH** (no docker socket to the agent). Server + frontend are the same FastAPI app; each TTS job runs as a **subprocess** in its job dir (keeps job lifetime decoupled from the web process; tool's `partN.flac` checkpoints give crash-resume).
- [x] Created working branch `container` (from `frontend`)
- [x] Added `Dockerfile-dev` — copy of `Dockerfile` + `openssh-server`, root SSH login, `EXPOSE 22`, `ENTRYPOINT ["/app/entrypoint-dev.sh"]`
- [x] Added `entrypoint-dev.sh` — starts `sshd`, creates `/data/{books,samples,jobs}`, keeps container alive (`tail -f /dev/null`)
- [x] Updated `outline.md` with the dev container + SSH flow

### Phase 5 — Dev environment live + architecture final review (2026-07-2x)
- [x] Dev container running; agent develops over SSH (`agent/development_environment.md`)
- [x] Architecture review with user — decisions confirmed:
  - HTMX + Jinja (no JS build)
  - CLI subprocess per job (supervisor in FastAPI app)
  - SSE tailing `progress.json` (written from subprocess stdout), polling fallback
  - Slug `<book-title-slug>-<YYYYMMDD-HHMM>`
  - No notifications
  - **New constraint: exactly ONE job transcribing at a time** (2 CLI instances won't fit in 1080 8 GB VRAM) → supervisor enforces single-job lock, Start/Resume return 409 when busy
- [x] Rewrote `agent/architecture.md` to the final single-container design (supervisor, single-job lock, confirmed decisions; dropped obsolete 2-service/worker-polling sections)

### Next
- [ ] Implement `epub2tts_chatterbox/web/` (FastAPI app + Jinja/HTMX frontend + job supervisor) in the container over SSH
