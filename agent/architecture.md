# Architecture — epub2tts-chatterbox Web Frontend

> Design-only document. No implementation.
> Goal: a simple Docker Composeable Web frontend wrapping `epub2tts-chatterbox`
> with durable, resumable jobs, live progress, and eBook dir browsing.

---

## 1. Design goals

| # | Requirement | Approach |
|---|-------------|----------|
| G1 | Docker Composeable | `docker-compose.yml` with 2 services + 1 volume |
| G2 | Conversion can take **days** | Durable: all state in files on a shared volume. Survives restarts. |
| G3 | Show running state on browser reopen | Read `state.json` from the volume — no in-memory dependency |
| G4 | Progress indicated | `state.json` updated by worker; polled/SSE by web |
| G5 | Browse mounted eBook dir | Web lists `.epub` files from the mounted folder |
| G6 | Two-step, step-1 interactive | State machine in `state.json`; web UI drives the review step |
| G7 | Dev: external GPU container runs the tool | Worker = any container that can write to the shared volume |
| G8 | Framework | **FastAPI** + static SPA |

**Core principle: files are the database.** No Postgres, no Redis. Each job is a directory with a `state.json`. The shared volume IS persistence.

---

## 2. Components (2 services + 1 volume)

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (SPA)                         │
└────────────────────┬────────────────────────────────────┘
                     │ HTTPS (REST + SSE)
┌────────────────────▼────────────────────────────────────┐
│  web  (FastAPI, CPU)                                    │
│  - Serves static SPA (React/Vue/build)                  │
│  - REST API: books, jobs, progress, audio               │
│  - SSE for live progress                                │
│  - Reads/writes state.json in job dirs                  │
│  - Enqueues by writing state to "queued"                │
└────────────────────┬────────────────────────────────────┘
                     │ reads/writes shared volume
┌────────────────────▼────────────────────────────────────┐
│  worker  (GPU container)                                │
│  - Polls for jobs in "queued" state                     │
│  - chdir into job dir, runs TTS                         │
│  - Updates state.json as it progresses                  │
│  - Writes progress.json, partN.flac, final .m4b         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  Shared volume: /data                                   │
│    /books/       ← host-mounted eBooks (RO)             │
│    /samples/     ← voice sample wavs                    │
│    /jobs/<slug>/ ← per-job workdir (see §5)             │
└──────────────────────────────────────────────────────────┘
```

**That's it. Two containers. One volume. No database. No queue service.**

---

## 3. Job lifecycle (state machine in `state.json`)

```
 DRAFT → EXTRACTING → AWAITING_REVIEW → TRANSCRIBING → ENCODING → DONE
                 ↘ FAILED / CANCELLED (any state)
```

| State | Who sets it | What happens |
|-------|-----------|--------------|
| `DRAFT` | Web (on job creation) | Book selected, params saved. Nothing run yet. |
| `EXTRACTING` | Web | `export_epub_to_dict()` runs (CPU, fast, seconds). Writes chapters to `state.json`. |
| `AWAITING_REVIEW` | Web | **Interactive step.** UI shows extracted chapters. User edits titles/text, picks naming method, sample, cover. Clicks "Start". |
| `TRANSCRIBING` | Worker | Long TTS step. Worker polls for `queued`/`transcribing` jobs, chdir into job dir, runs tool. Updates `state.json` progress. |
| `ENCODING` | Worker | ffmpeg concat + metadata + cover. Short. |
| `DONE` | Worker | `.m4b` ready. |
| `FAILED` | Worker | `error` field set. Can be resumed. |
| `CANCELLED` | Web | User cancelled. Checkpoints preserved for resume. |

**Resume:** On worker restart (or crash), it scans `/data/jobs/` for jobs in `TRANSCRIBING` state, chdir's in, re-runs the tool — the tool's built-in `partN.flac` / `pgraphsN.flac` checkpoints make it pick up where it left off. No external queue needed.

---

## 4. eBook browsing

- Host mounts eBooks folder → `/data/books` (read-only).
- `GET /api/books` → FastAPI lists `.epub` files (name, size, date).
- `GET /api/books/{name}/meta` → quick `export_epub_to_dict(..., interactive=False)` for preview (title, author, chapter count, cover).
- `GET /api/samples` → lists `/data/samples/*.wav|mp3`.
- User picks a book → POST `/api/jobs` → creates `DRAFT` job dir.

---

## 5. Per-job directory layout (THE state)

```
/data/jobs/<slug>/
    state.json          ← THE single source of truth
    book.txt            ← step-1 output (user-editable)
    cover.png           ← extracted or user-provided
    sample.wav          ← voice sample (if used)
    progress.json       ← live progress (worker writes, more granular)
    part1.flac          ← TTS checkpoints (tool writes)
    part2.flac
    ...
    <base> (<spk>).m4b  ← FINAL OUTPUT
    error.txt           ← if FAILED
```

### `state.json` schema

```json
{
  "id": "mybook-20260717",
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

**This one file is the entire "database" for a job.** Web reads it to render UI. Worker writes to it as it progresses. No external store.

### `progress.json` (optional, more granular / lower-level)

The tool already prints per-sentence progress. The worker wrapper can write a finer-grained file for SSE streaming. But `state.json` is the canonical state — `progress.json` is just a hot-update signal.

---

## 6. How the worker works (simple polling)

```python
# Pseudocode — the worker loop
while True:
    for job_dir in scan("/data/jobs/"):
        state = read(job_dir / "state.json")
        if state["state"] == "TRANSCRIBING":
            chdir(job_dir)
            # Resume-safe: tool checks for existing partN.flac
            run_tool(state["params"])  # or call read_book() directly
            update_state(job_dir, state="DONE")
            break  # one job at a time (single GPU)
    sleep(5)
```

- **Single GPU** → process one job at a time. Next job starts after current finishes.
- **No queue service** — the "queue" is just the directory scan. Jobs in `AWAITING_REVIEW` → user clicks Start → web sets state to `TRANSCRIBING` → worker picks it up on next poll.
- **Crash recovery** — on startup, worker re-scans; finds `TRANSCRIBING` jobs; resumes (tool checkpoints handle the rest).

---

## 7. Web → Worker communication

**No message broker.** Just:
1. Web writes `state.json` with `state: "TRANSCRIBING"` (user clicked Start).
2. Worker polls (every 3–5 s) for jobs in that state.
3. Worker updates `state.json` as it goes.
4. Web reads `state.json` / `progress.json` to show progress.

SSE endpoint in FastAPI:
```
GET /api/jobs/{id}/events
  → tails progress.json / state.json, pushes changes as SSE events
```

Polling fallback:
```
GET /api/jobs/{id}  → returns state.json contents
```

---

## 8. FastAPI endpoints

```
GET  /api/books                  # list .epub in /data/books
GET  /api/books/{name}/meta      # preview: title, author, chapters, cover
GET  /api/samples                # list voice samples
POST /api/jobs                   # create DRAFT {book, params}
GET  /api/jobs                   # list all jobs (scan /data/jobs/)
GET  /api/jobs/{id}              # read state.json
PATCH /api/jobs/{id}             # edit chapters/params (AWAITING_REVIEW only)
POST /api/jobs/{id}/start        # AWAITING_REVIEW → TRANSCRIBING
POST /api/jobs/{id}/cancel       # → CANCELLED
POST /api/jobs/{id}/resume       # FAILED/CANCELLED → TRANSCRIBING
GET  /api/jobs/{id}/events       # SSE progress stream
GET  /api/jobs/{id}/audio        # stream final .m4b
GET  /api/jobs/{id}/cover        # cover image
```

All of these are **file I/O** on the shared volume. No database calls.

---

## 9. Docker Compose (conceptual)

```yaml
services:
  web:
    build: ./web          # FastAPI + SPA
    volumes:
      - /data:/data       # shared volume
    ports:
      - "8080:8080"

  worker:
    image: pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime
    # (or the user's dev GPU container)
    volumes:
      - /data:/data
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
    # command: python /data/worker.py  (or mounted script)

volumes:
  # /data is a bind mount from the host in practice
```

**Dev override** (`docker-compose.dev.yml`):
- `worker` replaced by the user's external GPU container + shared folder + script.
- Same volume contract.

---

## 10. Reliability

| Failure | Recovery |
|---------|----------|
| Browser closed | No effect. Job continues in worker. Reopen → read `state.json`. |
| Worker crash/restart | Re-scans job dirs. Finds `TRANSCRIBING`. Tool resumes from `partN.flac`. |
| Web restart | Stateless. Re-reads job dirs. |
| Power loss | Same as worker crash. Checkpoints on disk. |
| Per-sentence TTS failure | Tool retries 3× (built-in). If all fail, logged, continues. |
| User cancels | Web sets `CANCELLED`. Worker stops. Checkpoints remain for later resume. |

---

## 11. Security (minimal)

- `/data/books` mounted read-only.
- API only exposes paths under `/data/` (no traversal).
- Single-user tool — no auth needed initially. (Optional: reverse proxy + basic auth for LAN exposure.)

---

## 12. What we eliminated (vs. previous design)

| Removed | Why |
|---------|-----|
| **Postgres** | `state.json` per job dir is the database. Sufficient for < 1000 jobs. |
| **Redis / message queue** | Worker polls the directory. One GPU = one job at a time. No broker needed. |
| **Separate "queue" service** | The directory scan IS the queue. |

**Net: 2 containers, 1 volume, files as state. Simple to reason about, simple to debug, simple to back up (tar the jobs dir).**

---

## 13. Open decisions

1. **SPA framework** — React, Vue, Svelte, or plain HTMX? (Suggest: simplest that works — maybe HTMX + Jinja for minimal JS.)
2. **Worker invocation** — CLI subprocess in job dir (simplest, works for dev) vs. direct function calls with shared model (better for prod, avoids model reload per job).
3. **Progress granularity** — poll `state.json` every 2 s vs. SSE tailing `progress.json`.
4. **Job naming/slug** — `<book-title-slug>-<timestamp>` to avoid collisions.
5. **Notifications** (optional) — desktop notification / email on DONE.
