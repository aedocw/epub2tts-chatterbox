# Progress Log

## 2026-10-29 — Bounded-memory chapter build + fixed silence pruning ✅

### Problem
- **A (RAM):** `read_book()` assembled each chapter with `combined += AudioSegment.from_file(file)`, decoding the whole chapter to raw PCM and copying on every `+=`. Peak RAM ≈ 2× chapter length (~173 MB per hour of 24 kHz mono 16-bit).
- **B (Silence):** Chatterbox emits long silences that were never pruned. Pruning the finished m4b would break chapter markers, so it had to happen before part files were finalized.

### Solution: one streaming ffmpeg call per chapter

Replaced the pydub chapter assembly (and `append_silence(files[-1], 2000)`) with a single streaming `ffmpeg` call via `build_part()`. It concatenates the paragraph FLACs, applies the fixed `SILENCE_FILTER`, then appends the 2 s chapter-end pad (`apad` after `silenceremove`, so the pad is never pruned).

#### Changes to `epub2tts_chatterbox.py` (642 lines)

1. **`SILENCE_FILTER`** — fixed filter: `silenceremove=stop_periods=-1:stop_duration=1.5:stop_threshold=-50dB`. No adaptive logic.
2. **`build_part(paragraph_files, partname, prune=True)`** — single streaming ffmpeg call: concat → silenceremove → apad → FLAC. Atomic write via `os.replace(tmp, partname)`. Deletes the temp list file.
3. **`get_duration()`** — replaced pydub decode with `ffprobe -show_entries format=duration` (header-only, no decode). Returns milliseconds as float.
4. **`generate_metadata()`** — accumulates durations as floats, rounds only when writing START/END. Added `assert len(files) == len(chapter_titles)`.
5. **`escape_ffmeta()`** — escapes `\`, `=`, `;`, `#`, `\n`, `\r` for FFMETADATAFILE. Applied to title, artist, album, and chapter titles.
6. **`get_book()`** — removed the per-`#`-line `chapter_titles.append()` calls. Titles now derived from the final `book_contents` list: `chapter_titles = [c["title"] for c in book_contents]`. Fixes the misalignment when `# Part One` is directly followed by `# Chapter 1`.
7. **Chapter-scoped paragraph temp names** — `pgraphs_c{chapter:04d}_p{pindex:05d}.flac` so leftovers from one chapter can never be picked up by another.
8. **`--no-prune` CLI flag** — passes `prune=False` to `read_book()` → `build_part()`.
9. **Stale temp cleanup** — `read_book()` removes `*.tmp.flac` and `*.list.txt` at startup.
10. **`append_silence()`** — kept for paragraph-level use (600 ms between sentences within a paragraph). Chapter-level 2 s pause now handled by `apad` in `build_part`.

#### Silenceremove semantics (verified on ffmpeg 4.2.7)

| Input | Output | Notes |
|-------|--------|-------|
| 1 s tone + 1.6 s silence + 1 s tone | 2.02 s | Silence ≥ 1.5 s → removed (~20 ms residual) |
| 2 s tone + 5 s silence + 2 s tone | 4.02 s | 5 s silence removed |
| 2 s tone + 2 s silence + 2 s tone | 4.02 s | 2 s silence removed |
| 1 s tone + 1.4 s silence + 1 s tone | 3.40 s | Below threshold → untouched |
| Two 2 s gaps (7 s total) | 3.04 s | Both removed independently |
| 600 ms paragraph pause | untouched | Below 1.5 s threshold |

Silences **< 1.5 s are untouched**. Silences **≥ 1.5 s are removed entirely** (not trimmed to 1.5 s), leaving ~20 ms residual.

### Test results (test_suite4.py on dev container, 2026-10-29)

**34 passed, 0 failed** ✅

| Test | Result |
|------|--------|
| **2. Pruning** | 13 s input with 5 s + 4 s silences → 6.04 s pruned (both removed + 2 s pad). `--no-prune` → 15.0 s. No temp files left. |
| **1. Memory** | Old pydub: 60.7 MB RSS delta. New `build_part`: **0.0 MB** Python RSS delta. ffmpeg child: **49.5 MB** peak RSS (streaming, flat). 10 min of audio. |
| **3. Markers** | 3 chapters in M4B. All chapter starts **0 ms** from cumulative part durations (well within 50 ms tolerance). Titles correct. |
| **4. Titles** | `# Part One` → `# Chapter 1` alignment: 2 chapters, 2 titles. Special chars (`=`, `;`, `#`, `\`, newline) all escape correctly. |
| **5. Resume** | Stale `.tmp.flac` and `.list.txt` cleaned. `part1.flac` preserved. `part2.flac` created atomically. No temp files left. |

### Files changed
- `epub2tts_chatterbox/epub2tts_chatterbox.py` — 642 lines (was ~580 before changes)
- `/tmp/test_suite4.py` — acceptance test suite (not committed; lives in `/data/devel/` on dev container)

### Non-goals honored
- No change to Chatterbox parameters, text splitting, or `epub_export`.
- No adaptive thresholds, no numpy/soundfile processing.
- `make_m4b` untouched.
- Part files from older runs used as-is (unpruned).

### Next
- [ ] A/B listen test: generate a real book with and without `--no-prune` and compare
- [ ] Commit to `dev` (awaiting approval)

---

## 2026-10-26 (later) — GPU-aware precision + production Dockerfile + README

### 1. GPU-aware precision (universal across GPUs) — `epub2tts_chatterbox.py`
- Problem: the 4060 Ti optimizations (bf16 autocast + TF32 + `cudnn.benchmark`) hurt
  the GTX 1080 (Pascal: no native bf16, crippled fp16 → bf16 autocast is slower than
  plain fp32). Made it GPU-aware instead of hardcoded, per compute capability.
- `read_book()` now computes:
  - `major, minor = torch.cuda.get_device_capability()`
  - `use_bf16 = (device == "cuda" and major >= 8)`
  - TF32 flags (`matmul.allow_tf32`, `cudnn.allow_tf32`) set **only** when `use_bf16`
  - `cudnn.benchmark` **removed** (neutral-to-negative for variable-length TTS on any GPU)
  - prints compute capability + bf16 decision for visibility
- `chatterbox_read()` gains `use_bf16` param (default False); wraps `model.generate()`
  in `torch.inference_mode()` **always**, plus `torch.autocast(bf16)` **iff** `use_bf16`
  (else `contextlib.nullcontext()`). Fixed the double `generate()` risk (only one call
  per sentence now). `inference_mode` kept for all GPUs (memory/overhead win).
- Result: 4060 Ti → bf16 + TF32 (fast); 1080 → fp32 (its fastest native path). No config needed.
- `py_compile` passes.
- **Caveat (from review):** bf16 can slightly change Chatterbox output quality on
  Ampere — worth an A/B listen on the 4060 Ti, not just a speed benchmark.

### 2. Production `Dockerfile` (no SSH)
- Rewritten: `COPY . /app/` (was `git clone` — would miss `web/`), installs ffmpeg/
  espeak-ng, `pip install .`, `EXPOSE 8080`, `VOLUME /data`.
- `ENTRYPOINT` now runs the **web UI** in the foreground:
  `python3 -m uvicorn epub2tts_chatterbox.web:app --host 0.0.0.0 --port 8080`.
- No `openssh-server` / sshd / key mounts (that stays in `Dockerfile-dev`).

### 3. `requirements.txt` — added missing web deps
- The web app imported fastapi/uvicorn/jinja2/pydantic but none were declared; a clean
  `pip install .` (and thus the new production image) would fail at startup.
- Added: `fastapi`, `uvicorn[standard]`, `jinja2`, `pydantic`.

### 4. `README.md`
- Docker section now matches the new image: `docker run -d -p 8080:8080 ...`, web UI at
  `http://<host>:8080`, books in `/data/<folder>/*.epub`, samples in `/data/speaker/`.
- Added "GPU precision is automatic" note (Ampere+ bf16/TF32, Pascal fp32).
- Features list: added Web UI + GPU-aware precision. Added a 2026-10-26 release note.

### 5. Agent docs
- `outline.md`: updated `Dockerfile` layout comment, web deps in `requirements.txt` note,
  and the pipeline internals to describe GPU-aware precision + removed `cudnn.benchmark`.

### Smoke test on the 1080 (deployed via SSH) — PASSED
- Deployed `epub2tts_chatterbox.py` to the **real import location**:
  `/opt/conda/lib/python3.10/site-packages/epub2tts_chatterbox/` (the package is a **non-editable**
  copy in site-packages, **not** `/app` — deploying to `/app` alone does nothing when run from
  `/data/devel`). Cleared stale `__pycache__` after deploy.
- Ran: `python -m epub2tts_chatterbox.epub2tts_chatterbox smoke_test.txt --sample /data/devel/sample3.wav`
  from `/data/devel` (3-sentence test book).
- Log confirms the GPU-aware decision on the **GTX 1080 (cc 6.1, Pascal)**:
  - `GPU compute capability: 6.1`
  - `Using bf16 autocast: False (inference_mode: always)`  → **fp32 path, as intended**
- Output `smoke_test (sample3).m4b`: valid AAC, 24 kHz mono, ~17.8 s, chapter metadata intact.
  No errors. Pascal fp32 path works end-to-end.

### Next
- [ ] A/B listen test on 4060 Ti (bf16 quality) — needs Ampere card; verify log shows `Using bf16 autocast: True`
- [ ] Build the production image locally and smoke-test the web UI end-to-end (`docker build` + `docker run`)
- [ ] Commit to `dev` (awaiting approval)

> **Dev-environment note (added 2026-10-26):** to test a changed Python file, copy it to
> `site-packages/epub2tts_chatterbox/` and clear `__pycache__` — `/app` is NOT on the import path
> when the package is installed non-editably.

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
