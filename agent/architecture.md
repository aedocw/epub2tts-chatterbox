# Architecture — epub2tts-chatterbox Web Frontend

> Final design (single GPU container). Supersedes the earlier 2-service (web + worker) draft.
> Goal: a Docker-Composeable Web frontend wrapping `epub2tts-chatterbox`
> with durable, resumable jobs, live progress, and eBook dir browsing.

---

## 1. Design goals

| # | Requirement | Approach |
|---|-------------|----------|
| G1 | Docker Composeable | `docker-compose.dev.yml` — 1 GPU container, 2 bind mounts |
| G2 | Conversion can take **days** | Durable: all state in files on the shared volume. Survives restarts. |
| G3 | Show running state on browser reopen | Read `state.json` from the volume — no in-memory dependency |
| G4 | Progress indicated | `progress.json` updated by job subprocess tail; SSE by web |
| G5 | Browse mounted eBook dir | Web lists `.epub` files from the mounted folder |
| G6 | Two-step, step-1 interactive | State machine in `state.json`; web UI drives the review step |
| G7 | Single GPU, 8 GB VRAM | **Exactly one conversion job runs at a time** (see §6) |
| G8 | Framework | **FastAPI** + HTMX/Jinja (no JS build step) |

**Core principle: files are the database.** No Postgres, no Redis. Each job is a
directory with a `state.json`. The shared volume IS persistence.

---

## 2. Components (1 container, 2 bind mounts)

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (HTMX)                        │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP (REST + SSE)
┌────────────────────▼────────────────────────────────────┐
│  Container: epub2tts-chatterbox-dev (GPU, 1080 8 GB)    │
│                                                         │
│  FastAPI app  (epub2tts_chatterbox.web)                 │
│  - Serves Jinja templates + HTMX (static)              │
│  - REST API: books, jobs, progress, audio              │
│  - SSE for live progress                               │
│  - Reads/writes state.json in job dirs                 │
│  - Job supervisor: spawns ONE `epub2tts-chatterbox`    │
│    CLI subprocess in the job dir, tails its stdout into │
│    progress.json, enforces the single-job lock         │
└────────────────────┬────────────────────────────────────┘
                     │ reads/writes shared volume
┌────────────────────▼────────────────────────────────────┐
│  /data  (bind mount → host /mnt/dm5/_ebook)             │
│    /books/       ← host-mounted eBooks (RO in spirit)   │
│    /samples/     ← voice sample wavs                    │
│    /jobs/<slug>/ ← per-job workdir (see §5)             │
└──────────────────────────────────────────────────────────┘
```

**One container. Two bind mounts (`/data`, HF model cache). No database. No queue service.**

The FastAPI process is both server **and** job supervisor. Each TTS job runs as a
separate **subprocess** (the CLI in its job dir), so:
- job lifetime is decoupled from the web process (uvicorn reload / crash is safe),
- the tool's built-in `partN.flac` checkpoints give crash-resume,
- killing the subprocess = clean cancel (checkpoints preserved).

---

## 3. Job lifecycle (state machine in `state.json`)

```
 DRAFT → AWAITING_REVIEW → TRANSCRIBING → ENCODING → DONE
                 ↘ FAILED / CANCELLED (any state after DRAFT)
```

| State | Who sets it | What happens |
|-------|-----------|--------------|
| `DRAFT` | Web (on job creation) | Book selected, params saved. Nothing run yet. |
| `AWAITING_REVIEW` | Web | After `export_epub_to_dict()` ran (CPU, fast, seconds). **Interactive step.** UI shows extracted chapters. User edits titles/text, picks naming method, sample, cover. Clicks "Start". |
| `TRANSCRIBING` | Web (Start/resume click, if no job is running) | Job supervisor spawns the CLI subprocess in the job dir. TTS runs for hours/days. |
| `ENCODING` | Supervisor (on process exit code 0, before `.m4b` verification) | ffmpeg concat + metadata + cover (happens inside the subprocess, supervisor just detects completion). |
| `DONE` | Supervisor | `.m4b` exists in job dir. |
| `FAILED` | Supervisor | Non-zero exit / exception. `error` field set from stderr tail. Can be resumed. |
| `CANCELLED` | Web | User cancelled → supervisor kills the subprocess. Checkpoints preserved for resume. |

**Note:** `EXTRACTING` is a transient, web-side-only phase (fast, in-request);
the job lands on disk already in `AWAITING_REVIEW`. No need to persist it.

**Resume:** On web restart, the supervisor scans `/data/jobs/` for jobs in
`TRANSCRIBING` state with no live subprocess → marks them `FAILED`
(`"interrupted — resumable"`), UI offers Resume. Resuming re-spawns the CLI in
the same job dir — the tool skips existing `partN.flac` / `pgraphsN.flac`.

---

## 4. eBook browsing

- Host mounts eBooks folder → `/data/books`.
- `GET /api/books` → FastAPI lists `.epub` files (name, size, date).
- `GET /api/books/{name}/meta` → `export_epub_to_dict(..., interactive=False)` for preview (title, author, chapter count, cover).
- `GET /api/samples` → lists `/data/samples/*.wav|mp3`.
- User picks a book → `POST /api/jobs` → creates `DRAFT` job dir, runs extraction, lands in `AWAITING_REVIEW`.

---

## 5. Per-job directory layout (THE state)

```
/data/jobs/<slug>/
    state.json          ← THE single source of truth
    book.txt            ← step-1 output (user-editable)
    cover.png           ← extracted or user-provided
    sample.wav          ← voice sample (if used)
    progress.json       ← live progress (supervisor writes from subprocess stdout)
    stdout.log          ← full CLI output (tail source, debug)
    part1.flac          ← TTS checkpoints (tool writes)
    part2.flac
    ...
    <base> (<spk>).m4b  ← FINAL OUTPUT
    error.txt           ← if FAILED (stderr tail)
```

### `state.json` schema

```json
{
  "id": "mybook-20260717-1430",
  "state": "AWAITING_REVIEW",
  "book_path": "/data/books/mybook.epub",
  "created_at": "2026-07-17T10:00:00Z",
  "updated_at": "2026-07-17T10:05:00Z",

  "params": {
    "naming": "auto",
    "notitles": false,
    "exaggeration": 0.7,
    "cfg_weight": 0.4,
    "sample": "samples/george.wav",
    "cover": "cover.png"
  },

  "book": {
    "title": "My Book",
    "author": "John Doe",
    "chapters": [
      {"ord": 1, "title": "Chapter 1", "text": "..."},
      {"ord": 2, "title": "Chapter 2", "text": "..."}
    ]
  },

  "progress": {
    "chapter": 5,
    "chapters_total": 42,
    "sentence": 12,
    "sentences_total": 87,
    "pct": 12.3,
    "elapsed_sec": 7200,
    "eta_sec": 50400
  },

  "output": {
    "path": "mybook (george).m4b",
    "size": null
  },

  "error": null
}
```

**This one file is the entire "database" for a job.** Web reads it to render UI.
Supervisor + subprocess write to it as they progress. No external store.

### `progress.json` (hot-update signal)

The supervisor tails the subprocess stdout (tqdm / per-chapter Elapsed-ETA
lines), parses sentence/chapter counts, and writes `progress.json` + mirrors a
summary into `state.json.progress`. SSE tails `progress.json` for live UI
updates; plain polling of `state.json` is the fallback.

---

## 6. Job supervision — single-job lock

**Hard constraint: exactly ONE job in `TRANSCRIBING` at a time.**
Two parallel CLI instances would each load the Chatterbox model into the
1080's 8 GB VRAM → OOM. The supervisor enforces this:

```python
# Supervisor (inside FastAPI app, background task)
async def supervise():
    while True:
        # 1. Track our own subprocess if running
        if proc is not None:
            update progress.json from stdout tail
            if proc exited:
                finalize (DONE / FAILED), proc = None
        # 2. Otherwise, pick the next queued job
        else:
            job = oldest job in state AWAITING_REVIEW+started / TRANSCRIBING-orphan
            if job: spawn CLI subprocess in job dir
        await sleep(2)
```

- Start/resume endpoints **refuse** (409) if a job is already running:
  `"another job is transcribing — only one GPU job allowed"`.
- On startup: any orphaned `TRANSCRIBING` job (no live proc) → `FAILED`
  with `error: "interrupted — resumable"`.
- Progress source = subprocess stdout (tqdm per chapter, Elapsed/ETA lines)
  parsed into `progress.json`.

---

## 7. Web → Job communication

**No message broker.** The supervisor lives in the FastAPI process and
spawns/kills the CLI subprocess directly. Files on `/data` remain the durable
contract, so a web restart loses nothing:

1. User clicks Start → web sets `state.json` → `TRANSCRIBING` → supervisor
   spawns the subprocess in the job dir (within ~2 s).
2. Supervisor tails stdout → `progress.json` + `state.json`.
3. Web reads `state.json` / `progress.json` to render progress (SSE).

---

## 8. FastAPI endpoints

```
GET  /api/books                  # list .epub in /data/books
GET  /api/books/{name}/meta      # preview: title, author, chapters, cover
GET  /api/samples                # list voice samples
POST /api/jobs                   # create DRAFT → extract → AWAITING_REVIEW
GET  /api/jobs                   # list all jobs (scan /data/jobs/)
GET  /api/jobs/{id}              # read state.json
PATCH /api/jobs/{id}             # edit chapters/params (AWAITING_REVIEW only)
POST /api/jobs/{id}/start        # AWAITING_REVIEW → TRANSCRIBING (409 if busy)
POST /api/jobs/{id}/cancel       # → CANCELLED (supervisor kills subprocess)
POST /api/jobs/{id}/resume       # FAILED/CANCELLED → TRANSCRIBING (409 if busy)
GET  /api/jobs/{id}/events       # SSE progress stream (tails progress.json)
GET  /api/jobs/{id}/audio        # stream final .m4b
GET  /api/jobs/{id}/cover        # cover image
```

All of these are **file I/O** on the shared volume. No database calls.

---

## 9. Docker Compose (dev, as built)

See `docker-compose.dev.yml` in the repo root. Summary:

```yaml
services:
  web:  # single container, GPU
    build: . (Dockerfile-dev)
    volumes:
      - /mnt/models/epub2tts:/root/.cache/huggingface
      - /mnt/dm5/_ebook:/data
      - <ssh keys>:/root/.ssh:ro
    ports:
      - "2222:22"     # dev SSH
      - "8080:8080"   # FastAPI
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1            # GPU index 1 on host
```

Dev flow: SSH in, edit `/app` on branch `dev`, `pip install -e .`,
run uvicorn. Production: same image, drop SSH, run the supervisor as the
service command.

---

## 10. Reliability

| Failure | Recovery |
|---------|----------|
| Browser closed | No effect. Job continues in subprocess. Reopen → read `state.json`. |
| Web/uvicorn restart | Supervisor re-scans. Orphaned `TRANSCRIBING` → `FAILED (resumable)`. |
| Subprocess crash | Non-zero exit → `FAILED`, stderr tail in `error.txt`. Resume re-spawns in same dir; `partN.flac` checkpoints skip finished chapters. |
| Power loss | Same as subprocess crash. Checkpoints on disk. |
| Per-sentence TTS failure | Tool retries 3× (built-in). If all fail, logged, continues. |
| User cancels | Web sets `CANCELLED`; supervisor kills subprocess. Checkpoints remain for later resume. |
| Second Start click | Rejected with 409 — single-job lock. |

---

## 11. Security (minimal)

- `/data/books` treated as read-only by the app (no write endpoints for it).
- API only exposes paths under `/data/` (no traversal; job IDs are slugs, not paths).
- Single-user tool — no auth needed initially. (Optional: reverse proxy + basic auth for LAN exposure.)

---

## 12. Decided (was: open decisions)

| Decision | Choice |
|----------|--------|
| SPA framework | **HTMX + Jinja templates** — no build step, minimal JS |
| Worker invocation | **CLI subprocess per job** in its job dir (keeps model lifecycle per-job; 1080 8 GB fits one instance) |
| Progress granularity | **SSE tailing `progress.json`**, written by the supervisor from subprocess stdout; polling `state.json` as fallback |
| Job naming/slug | `<book-title-slug>-<YYYYMMDD-HHMM>` |
| Notifications | **Skipped** (browser shows progress via SSE) |
| Concurrency | **Exactly one job transcribing at a time** (VRAM constraint) |

---

## 13. What we eliminated (vs. previous designs)

| Removed | Why |
|---------|-----|
| **Postgres** | `state.json` per job dir is the database. Sufficient for < 1000 jobs. |
| **Redis / message queue** | Supervisor in-process; directory scan for discovery. One GPU = one job. |
| **Separate worker container/service** | Single container: FastAPI app is server + supervisor; jobs are subprocesses. |
| **In-request extraction state (`EXTRACTING` persisted)** | Extraction is fast and in-request; job lands in `AWAITING_REVIEW` on disk. |

**Net: 1 container, 2 mounts, files as state. Simple to reason about, simple to debug, simple to back up (tar the jobs dir).**
