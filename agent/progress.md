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

### Next (pending user direction)
- [ ] Await confirmation of architecture / open decisions
- [ ] When dev shared folder + GPU script provided → wire up live testing
- [ ] (Not now) Implementation
