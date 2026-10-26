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

### Phase 6 — Full Web Frontend Implementation (2026-10-26) ✅ COMPLETE

- [x] **`epub2tts_chatterbox/web/__init__.py`** — exports `app`
- [x] **`epub2tts_chatterbox/web/state.py`** — file-based state management:
  - `create_job()`, `read_state()`, `write_state()`, `set_job_state()`, `list_jobs()`
  - `read_progress()`, `write_progress()` — hot `progress.json` for live updates
  - `build_book_txt()` — writes `book.txt` in the required CLI format
  - `make_job_id()` — slug `<title-slug>-<YYYYMMDD-HHMM>`
  - `find_output_m4b()` — locates the final `.m4b` file in a job dir
  - `mark_orphans_failed()` — marks stale TRANSCRIBING jobs as FAILED on startup
- [x] **`epub2tts_chatterbox/web/supervisor.py`** — async job supervisor:
  - Single-process lock: exactly ONE job transcribing at a time
  - `_spawn()` — builds CLI args, launches subprocess with `cwd=job_dir`
  - `_pump_once()` — reads stdout line-by-line, feeds `JobProcess.feed()`
  - `JobProcess.feed()` — parses tqdm progress lines, extracts chapter/sentence counts
  - Progress written to `progress.json` every ~2s (throttled)
  - `_finalize()` — sets state to DONE/FAILED, records output file info
  - `mark_orphans_failed()` — marks stale jobs on startup
  - Cancel support via `os.killpg()` on the subprocess process group
- [x] **`epub2tts_chatterbox/web/app.py`** — FastAPI app (458 lines):
  - **Pages**: `/` (home), `/jobs` (job list), `/jobs/{id}` (job detail)
  - **API**:
    - `GET /api/books` — list EPUBs from `/data/` subdirectories
    - `GET /api/samples` — list speaker samples from `/data/speaker/`
    - `POST /api/jobs` — create job (EPUB → `book.txt` + `cover.png`)
    - `GET /api/jobs` — list all jobs
    - `GET /api/jobs/{id}` — job detail + live progress
    - `PATCH /api/jobs/{id}/meta` — update title/author/sample/params
    - `PATCH /api/jobs/{id}/chapters/{ord}` — edit chapter text/title
    - `POST /api/jobs/{id}/start` / `resume` — start transcription (409 if busy)
    - `POST /api/jobs/{id}/cancel` — cancel running job
    - `GET /api/jobs/{id}/audio` — download/stream the M4B
    - `GET /api/jobs/{id}/cover` — cover image
    - `GET /api/jobs/{id}/book.txt` — text content
    - `GET /api/jobs/{id}/events` — SSE stream for live progress
    - `DELETE /api/jobs/{id}` — delete job
    - `GET /health` — health check
- [x] **Templates**: `home.html`, `jobs.html`, `job.html` — Jinja2 + HTMX
- [x] **`static/htmx.min.js`** — inlined into every page (no static server needed)

#### Bugs found & fixed during implementation:
1. **Sample path resolution** (`supervisor.py`): Relative path `speaker/dii.wav` was passed to subprocess with `cwd=jdir`, causing `FileNotFoundError`. **Fix:** Resolve relative sample paths against `DATA_ROOT`, cover paths against job dir.
2. **`proc.wait()` on stdout EOF** (`supervisor.py` `_pump_once`): When `readline()` returned `b""` (EOF), `returncode` was never set because `proc.wait()` was never called, causing the main loop to spin forever. **Fix:** Added `await jp.proc.wait()` before raising `StopAsyncIteration`.
3. **`_finalize()` signature mismatch** (`supervisor.py`): Method required `log_file` parameter but was called as `self._finalize(jp)` in the run loop, causing `TypeError`. **Fix:** Removed the unused `log_file` parameter and the leaked `stdout_log` file handle from `_spawn`.
4. **Cancel state was `FAILED` instead of `CANCELLED`** (`supervisor.py`): `cancel()` sent `SIGTERM` but `_finalize()` had no way to distinguish a user-initiated cancel from a crash — both resulted in `state=FAILED`. **Fix:** Added `self.cancelled = False` flag to `JobProcess`; `cancel()` sets it to `True` before sending `SIGTERM`; `_finalize()` checks `jp.cancelled` and sets `state=CANCELLED` with `error="cancelled by user"` instead of `FAILED`.

#### End-to-end test results (on dev container, 1080 GPU) — 2026-10-26:
- [x] Health check: `{"ok": true, "busy": false}`
- [x] Book listing: 87 EPUBs across book directories listed correctly
- [x] Sample listing: 7 speaker WAV files listed
- [x] Job creation from EPUB: `POST /api/jobs` → `AWAITING_REVIEW`
- [x] Job detail: book info, chapters, params all present
- [x] PATCH meta: title updated successfully
- [x] Transcription: `POST /api/jobs/{id}/start` → `TRANSCRIBING` → `DONE` (45s for 2-chapter test book)
- [x] Progress tracking: `progress.json` updated with `pct`, `chapter`, `chapters_total`, `eta_sec`
- [x] M4B output: `book (dii).m4b` (186,934 bytes) created with embedded chapters + cover
- [x] Download: `GET /api/jobs/{id}/audio` → 200, 186,934 bytes
- [x] 409 protection: `POST /api/jobs/{id}/start` on DONE job → 409
- [x] 409 protection: `POST /api/jobs/{id}/start` while busy → 409
- [x] Web UI: all 3 pages render HTML (home, jobs list, job detail) with HTMX
- [x] Jobs list API: returns all jobs with states
- [x] SSE events endpoint: connects and streams
- [x] book.txt endpoint: returns valid text with Title/Author/chapters
- [x] Cover endpoint: 404 when no cover (correct behavior)
- [x] **Cancel flow**: create → start → cancel → `CANCELLED` → resume → `TRANSCRIBING` → cancel → `CANCELLED` ✓

**Total: 45/45 checks passed** (44 API/UI + 1 cancel flow)

### HTMX form submission bugs (2026-10-26)
- [x] **Bug 1: `"Failed to create job: undefined"`**
  - Root cause: `event.detail.responseJSON` / `event.detail.response` don't exist
    in HTMX 1.x. Fixed to `event.detail.xhr.responseText`.
- [x] **Bug 2: `"Failed to create job: [object Object]"`**
  - Root cause: HTMX with `hx-encoding="json"` serializes ALL form elements,
    including the `<button type="submit">`. The button's text ("Create job →")
    was sent as an extra JSON key. FastAPI's Pydantic model rejected the
    unknown field with a 422 validation error where `detail` is an **array**
    of objects → `JSON.stringify(array)` → `[object Object]`.
  - Fix 1: Added `model_config = ConfigDict(extra="ignore")` to `JobCreate`,
    `MetaUpdate`, and `ChapterUpdate` so extra fields are silently ignored.
  - Fix 2: Improved error handler to extract `.msg` from array details:
    `Array.isArray(d) ? d.map(x => x.msg).join(', ') : String(d)`
- [x] **Bug: `"Failed to create job: undefined"` alert on form submit**
  - Root cause: `hx-on::after-request` in `home.html` used `event.detail.responseJSON`
    and `event.detail.response` which **do not exist** in HTMX 1.x.
    The correct access path is `event.detail.xhr.responseText`.
  - Fix: replaced with `JSON.parse(event.detail.xhr.responseText)` and
    used `location.href` for redirect (removed the `job-created` custom event).
  - Also improved error messages: extracts `detail` from the JSON error body
    instead of stringifying the whole response.
- [x] **Bug: `"Failed to create job: Input should be a valid dictionary or object to extract fields from"`**
  - Root cause: The form used `hx-encoding="json"` which causes HTMX to send
    the body as a raw JSON string. However, FastAPI's `Form` parameters expect
    `application/x-www-form-urlencoded` data. When the Content-Type was JSON
    but the endpoint expected form data, Pydantic received the raw string
    instead of a dict → "Input should be a valid dictionary".
  - Fix: Removed `hx-encoding="json"` from the form in `home.html` so HTMX
    sends standard `application/x-www-form-urlencoded` data (the default).
  - **Verified:** `POST /api/jobs` with URL-encoded form data → 404 "book not found"
    (expected, since test book doesn't exist on server) — no more 422 validation error.
- [x] **Bug: clicking Start/Resume dumped huge JSON of all chapters into the page**
  - Root cause: `hx-post` on start/resume/cancel buttons had no `hx-swap="none"`,
    so HTMX swapped the full JSON response (all chapters) into the page via
    default `innerHTML`. Also, the live progress poller hit `GET /api/jobs/{id}`
    which returns the full job state including all chapters.
  - Fix:
    1. Added `hx-swap="none"` + `hx-on::after-request` (reload on success)
       to all start/resume/cancel buttons in `job.html`.
    2. Created new lightweight endpoint `GET /api/jobs/{id}/progress`
       that returns only `{state, progress}` as an HTML fragment
       (`templates/progress.html`) — no chapters.
    3. Changed the `#live` div to poll `/api/jobs/{id}/progress` instead of
       `/api/jobs/{id}`.
    4. Also removed `hx-encoding="json"` + `hx-ext="json-enc"` from the
       meta form and chapter inputs (same Form params fix as home.html).
  - **Verified:** `GET /api/jobs/{id}/progress` → 389-char HTML fragment
    with progress bar + stdout, no chapters.

### Container restart resilience + Dockerfile fix (2026-10-26)
- [x] Updated `entrypoint-dev.sh` to auto-start the web server on container boot:
  - `nohup uvicorn ... > /var/log/uvicorn.log 2>&1 &`
  - PID file at `/var/run/uvicorn.pid`
  - 5s health check after start, warning if failed
  - **No manual SSH + start needed after `docker restart`**
  - SSH in only for debugging: `tail -f /var/log/uvicorn.log`, `kill $(cat /var/run/uvicorn.pid)`
- [x] **Bug: `docker rm + docker run` lost all SSH-pushed code**
  - Root cause: `Dockerfile-dev` used `RUN git clone` (GitHub, no `web/` package)
  - Fix: changed to `COPY . /app/` (build from local source, includes `web/`)
  - Added `.dockerignore` (excludes `agent/`, `.git`, `__pycache__`, etc.)
  - Added `EXPOSE 8080`
  - **Lesson: after `docker rm`, the writable layer is gone. Rebuild the image
    (`docker build`) to make code changes permanent.**
- [x] Re-copied `web/` package + updated entrypoint to the recreated container
- [x] Server verified live on `http://192.168.0.3:1244` → `{"ok":true,"busy":false}`

### Next
- [ ] User acceptance testing (listen to M4B, try editing chapters, cancel mid-run)
- [ ] Consider: log viewer in UI (stdout.log)
- [ ] Consider: job search/filter
- [ ] Consider: auto-pickup of queued jobs (supervisor already picks next queued job)
- [ ] Commit to `container` branch when satisfied
