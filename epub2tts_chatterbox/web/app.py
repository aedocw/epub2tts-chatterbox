"""
epub2tts-chatterbox Web frontend.

FastAPI + Jinja/HTMX single-container app. Files under /data are the database.
Run:  /opt/conda/bin/python3 -m uvicorn epub2tts_chatterbox.web:app --host 0.0.0.0 --port 8080
"""

import asyncio
import json
import os
import shutil
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import (FileResponse, PlainTextResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

from . import state as st
from .supervisor import Supervisor

DATA_ROOT = os.environ.get("EPUB2TTS_DATA", "/data")
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# read htmx once at import time to inline in every page (no static server needed)
HTMX_SRC = open(os.path.join(STATIC_DIR, "htmx.min.js"), encoding="utf-8").read()

app = FastAPI(title="epub2tts-chatterbox")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
supervisor = Supervisor(DATA_ROOT)


# ------------------------------------------------------------------ lifecycle
@app.on_event("startup")
async def startup():
    os.makedirs(os.path.join(DATA_ROOT, "jobs"), exist_ok=True)
    asyncio.create_task(supervisor.run())


@app.on_event("shutdown")
async def shutdown():
    await supervisor.stop()


# --------------------------------------------------------------------- models
class JobCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    book: str                      # filename inside /data/books
    naming: Optional[str] = "auto"
    notitles: bool = False
    exaggeration: Optional[float] = 0.7
    cfg_weight: Optional[float] = 0.4
    sample: Optional[str] = None   # filename inside /data/samples (or relative path)


class MetaUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = None
    author: Optional[str] = None
    sample: Optional[str] = None
    exaggeration: Optional[float] = None
    cfg_weight: Optional[float] = None
    notitles: Optional[bool] = None


class ChapterUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[str] = None
    text: Optional[str] = None


# ------------------------------------------------------------------- helpers
def _job_or_404(job_id: str) -> dict:
    state = st.read_state(DATA_ROOT, job_id)
    if state is None:
        raise HTTPException(404, "job not found")
    return state


def _safe_data_path(rel: str) -> str:
    """Resolve a user-supplied path under /data; refuse traversal/absolute."""
    if rel.startswith("/"):
        raise HTTPException(400, "path must be relative to /data")
    full = os.path.normpath(os.path.join(DATA_ROOT, rel))
    if not full.startswith(DATA_ROOT + os.sep) and full != DATA_ROOT:
        raise HTTPException(400, "invalid path")
    return full


# directories under /data that are not book folders
_NON_BOOK_DIRS = {"jobs", "speaker", "samples", "devel", "_finished",
                  "defective", "maoyuu", "__pycache__"}


def _list_epubs() -> list[dict]:
    """Scan immediate subdirectories of /data/ for .epub files."""
    out = []
    if not os.path.isdir(DATA_ROOT):
        return out
    for entry in sorted(os.listdir(DATA_ROOT)):
        sub = os.path.join(DATA_ROOT, entry)
        if not os.path.isdir(sub) or entry in _NON_BOOK_DIRS:
            continue
        for name in sorted(os.listdir(sub)):
            path = os.path.join(sub, name)
            if name.lower().endswith(".epub") and os.path.isfile(path):
                rel = os.path.join(entry, name)  # relative to /data
                out.append({
                    "name": rel,
                    "size": os.path.getsize(path),
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path))),
                })
    return out


def _list_samples() -> list[dict]:
    samples_dir = os.path.join(DATA_ROOT, "speaker")
    out = []
    if os.path.isdir(samples_dir):
        for name in sorted(os.listdir(samples_dir)):
            path = os.path.join(samples_dir, name)
            if name.lower().endswith((".wav", ".mp3")) and os.path.isfile(path):
                out.append({
                    "name": name,
                    "rel": os.path.join("speaker", name),  # relative to /data
                    "size": os.path.getsize(path),
                })
    return out


# --------------------------------------------------------------------- pages
@app.get("/")
async def home(request: Request):
    books = _list_epubs()
    samples = _list_samples()
    jobs = st.list_jobs(DATA_ROOT)
    return templates.TemplateResponse("home.html", {
        "request": request, "htmx_src": HTMX_SRC,
        "books": books, "samples": samples,
        "jobs": jobs, "running": supervisor.running_job_id(),
    })


@app.get("/jobs")
async def jobs_page(request: Request):
    return templates.TemplateResponse("jobs.html", {
        "request": request, "htmx_src": HTMX_SRC,
        "jobs": st.list_jobs(DATA_ROOT),
        "running": supervisor.running_job_id(),
    })


@app.get("/jobs/{job_id}")
async def job_page(request: Request, job_id: str):
    state = _job_or_404(job_id)
    jdir = st.job_dir(DATA_ROOT, job_id)
    book_txt = os.path.join(jdir, "book.txt")
    chapters_view = state.get("book", {}).get("chapters", [])
    text_visible = len(chapters_view) <= 200  # don't render giant books inline
    return templates.TemplateResponse("job.html", {
        "request": request, "htmx_src": HTMX_SRC,
        "job": state,
        "samples": _list_samples(),
        "book_txt": book_txt,
        "text_visible": text_visible,
    })


# ---------------------------------------------------------------------- API
@app.get("/api/books")
async def api_books():
    return _list_epubs()


@app.get("/api/books/{name:path}/meta")
async def api_book_meta(name: str):
    path = _safe_data_path(name)
    if not os.path.isfile(path) or not path.lower().endswith(".epub"):
        raise HTTPException(404, "book not found")
    from epub2tts_chatterbox.epub_export import export_epub_to_dict
    data = export_epub_to_dict(path, naming_method="auto",
                               verbose=False, interactive=False)
    chapters = data.get("chapters", [])
    return {
        "title": data.get("title"),
        "author": data.get("author"),
        "chapter_count": len(chapters),
        "has_cover": data.get("cover_image") is not None,
        "preview": [
            {"ord": i + 1, "title": c.get("title")}
            for i, c in enumerate(chapters[:30])
        ],
    }


@app.get("/api/samples")
async def api_samples():
    return _list_samples()


@app.post("/api/jobs")
async def api_create_job(
    book: str = Form(...),
    naming: Optional[str] = Form("auto"),
    sample: Optional[str] = Form(None),
    notitles: Optional[bool] = Form(False),
    exaggeration: Optional[str] = Form(None),
    cfg_weight: Optional[str] = Form(None),
):
    book_path = _safe_data_path(book)
    if not os.path.isfile(book_path) or not book_path.lower().endswith(".epub"):
        raise HTTPException(404, "book not found")
    book_name = os.path.basename(book_path)

    from epub2tts_chatterbox.epub_export import export_epub_to_dict
    data = export_epub_to_dict(book_path, naming_method=naming,
                               verbose=False, interactive=False)

    # sample: accept name in /data/samples or a relative path under /data
    sample_rel = sample if sample else None
    if sample_rel:
        sample_path = _safe_data_path(sample_rel)
        if not os.path.isfile(sample_path):
            raise HTTPException(404, f"sample not found: {sample}")

    # convert optional numeric fields from string
    exag = float(exaggeration) if exaggeration else 0.7
    cfg_w = float(cfg_weight) if cfg_weight else 0.4

    title = data.get("title") or book_name
    job_id = st.make_job_id(title)
    # avoid collision if created in the same minute
    while os.path.isdir(st.job_dir(DATA_ROOT, job_id)):
        job_id = job_id + "-x"

    chapters = [{"ord": i + 1, "title": c.get("title"),
                 "text": c.get("text", ""),
                 "paragraphs": c.get("paragraphs", [])}
                for i, c in enumerate(data.get("chapters", []))]

    state = {
        "id": job_id,
        "state": st.AWAITING_REVIEW,
        "book_path": book_path,
        "params": {
            "naming": naming,
            "notitles": notitles,
            "exaggeration": exag,
            "cfg_weight": cfg_w,
            "sample": sample_rel,
            "cover": "cover.png",
        },
        "book": {
            "title": title,
            "author": data.get("author", "Unknown Author"),
            "chapters": chapters,
        },
        "progress": None,
        "output": None,
        "error": None,
    }
    jdir = st.create_job(DATA_ROOT, state)

    # write book.txt + cover immediately (review edits rewrite book.txt)
    st.build_book_txt(jdir, title, state["book"]["author"], chapters)
    if data.get("cover_image") is not None:
        try:
            data["cover_image"].save(os.path.join(jdir, "cover.png"))
        except OSError:
            pass
    st.write_state(DATA_ROOT, state)
    return {"id": job_id, "state": state["state"]}


@app.get("/api/jobs")
async def api_jobs():
    return st.list_jobs(DATA_ROOT)


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    state = _job_or_404(job_id)
    live = st.read_progress(DATA_ROOT, job_id)
    if live is not None:
        state["progress"] = live
    return state


@app.patch("/api/jobs/{job_id}/meta")
async def api_update_meta(
    job_id: str,
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    sample: Optional[str] = Form(None),
    exaggeration: Optional[str] = Form(None),
    cfg_weight: Optional[str] = Form(None),
    notitles: Optional[str] = Form(None),
):
    state = _job_or_404(job_id)
    if state["state"] not in (st.AWAITING_REVIEW, st.FAILED, st.CANCELLED):
        raise HTTPException(409, f"cannot edit job in state {state['state']}")
    if title is not None:
        state["book"]["title"] = title
    if author is not None:
        state["book"]["author"] = author
    params = state["params"]
    if sample is not None:
        if sample == "":
            params["sample"] = None
        else:
            path = _safe_data_path(sample)
            if not os.path.isfile(path):
                raise HTTPException(404, f"sample not found: {sample}")
            params["sample"] = sample
    if exaggeration is not None and exaggeration != "":
        params["exaggeration"] = float(exaggeration)
    if cfg_weight is not None and cfg_weight != "":
        params["cfg_weight"] = float(cfg_weight)
    if notitles is not None:
        params["notitles"] = notitles in ("true", "True", "1")
    st.write_state(DATA_ROOT, state)
    return {"saved": True}


@app.patch("/api/jobs/{job_id}/chapters/{ord}")
async def api_update_chapter(
    job_id: str,
    ord: int,
    title: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
):
    state = _job_or_404(job_id)
    if state["state"] not in (st.AWAITING_REVIEW, st.FAILED, st.CANCELLED):
        raise HTTPException(409, f"cannot edit job in state {state['state']}")
    chapters = state["book"]["chapters"]
    if not (1 <= ord <= len(chapters)):
        raise HTTPException(404, "chapter not found")
    ch = chapters[ord - 1]
    if title is not None:
        ch["title"] = title
    if text is not None:
        ch["text"] = text
        ch["paragraphs"] = [p for p in text.split("\n") if p.strip()]
    # rebuild book.txt
    jdir = st.job_dir(DATA_ROOT, job_id)
    st.build_book_txt(jdir, state["book"]["title"], state["book"]["author"], chapters)
    st.write_state(DATA_ROOT, state)
    return {"saved": True}


@app.get("/api/jobs/{job_id}/state")
async def api_job_state(job_id: str):
    state = _job_or_404(job_id)
    live = st.read_progress(DATA_ROOT, job_id)
    if live is not None:
        state["progress"] = live
    return state


@app.get("/api/jobs/{job_id}/progress")
async def api_job_progress(job_id: str, request: Request):
    """Lightweight progress HTML fragment for HTMX polling — no chapters."""
    state = _job_or_404(job_id)
    live = st.read_progress(DATA_ROOT, job_id)
    return templates.TemplateResponse("progress.html", {
        "request": request, "job": state, "progress": live,
    })


def _start_job(job_id: str):
    state = _job_or_404(job_id)
    if state["state"] not in (st.AWAITING_REVIEW, st.FAILED, st.CANCELLED):
        raise HTTPException(409, f"cannot start job in state {state['state']}")
    if supervisor.is_busy():
        raise HTTPException(409,
                            "another job is transcribing — only one GPU job allowed")
    jdir = st.job_dir(DATA_ROOT, job_id)
    if not os.path.isfile(os.path.join(jdir, "book.txt")):
        raise HTTPException(400, "job has no book.txt")
    # validate the text (Title/Author/# present)
    with open(os.path.join(jdir, "book.txt"), encoding="utf-8") as f:
        content = f.read()
    has_title = content.startswith("Title: ")
    has_author = "\nAuthor: " in content
    has_chapter = any(line.strip().startswith("#") for line in content.splitlines())
    if not (has_title and has_author and has_chapter):
        raise HTTPException(400,
                            "book.txt is missing Title/Author/chapter lines")
    st.set_job_state(DATA_ROOT, job_id, st.TRANSCRIBING, error=None)
    return st.read_state(DATA_ROOT, job_id)


@app.post("/api/jobs/{job_id}/start")
async def api_start_job(job_id: str):
    return _start_job(job_id)


@app.post("/api/jobs/{job_id}/resume")
async def api_resume_job(job_id: str):
    return _start_job(job_id)


@app.post("/api/jobs/{job_id}/cancel")
async def api_cancel_job(job_id: str):
    state = _job_or_404(job_id)
    if state["state"] == st.TRANSCRIBING:
        supervisor.cancel(job_id)
        # give the process a moment to die, then mark CANCELLED
        async def _do_cancel():
            for _ in range(40):
                await asyncio.sleep(0.5)
                if not supervisor.is_busy():
                    break
            s = st.read_state(DATA_ROOT, job_id)
            if s is not None and s["state"] == st.TRANSCRIBING:
                st.set_job_state(DATA_ROOT, job_id, st.CANCELLED,
                                 error="cancelled — checkpoints kept, resumable")
        asyncio.create_task(_do_cancel())
        return {"state": "cancelling"}
    elif state["state"] in (st.AWAITING_REVIEW,):
        st.set_job_state(DATA_ROOT, job_id, st.CANCELLED,
                         error="cancelled before start")
        return st.read_state(DATA_ROOT, job_id)
    else:
        raise HTTPException(409, f"cannot cancel job in state {state['state']}")


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str):
    _job_or_404(job_id)

    last = None
    while True:
        state = st.read_state(DATA_ROOT, job_id)
        if state is None:
            break
        live = st.read_progress(DATA_ROOT, job_id)
        if live is not None:
            state["progress"] = live
        cur = json.dumps(state)
        if cur != last:
            yield f"data: {cur}\n\n"
            last = cur
        if state["state"] in st.TERMINAL_STATES:
            break
        await asyncio.sleep(1)


@app.get("/api/jobs/{job_id}/audio")
async def api_job_audio(job_id: str):
    jdir = st.job_dir(DATA_ROOT, job_id)
    m4b = st.find_output_m4b(jdir)
    if not m4b:
        raise HTTPException(404, "no audio yet")
    return FileResponse(m4b, media_type="audio/mp4",
                         filename=os.path.basename(m4b))


@app.get("/api/jobs/{job_id}/cover")
async def api_job_cover(job_id: str):
    jdir = st.job_dir(DATA_ROOT, job_id)
    cover = os.path.join(jdir, "cover.png")
    if not os.path.isfile(cover):
        raise HTTPException(404, "no cover")
    return FileResponse(cover, media_type="image/png")


@app.get("/api/jobs/{job_id}/book.txt")
async def api_job_book_txt(job_id: str):
    jdir = st.job_dir(DATA_ROOT, job_id)
    path = os.path.join(jdir, "book.txt")
    if not os.path.isfile(path):
        raise HTTPException(404, "no book.txt")
    return PlainTextResponse(open(path, encoding="utf-8").read())


@app.delete("/api/jobs/{job_id}")
async def api_delete_job(job_id: str):
    state = _job_or_404(job_id)
    if state["state"] == st.TRANSCRIBING:
        raise HTTPException(409, "cancel the job first")
    jdir = st.job_dir(DATA_ROOT, job_id)
    shutil.rmtree(jdir, ignore_errors=True)
    return {"deleted": job_id}


# ---------------------------------------------------------------------- misc
@app.get("/health")
async def health():
    return {"ok": True, "busy": supervisor.is_busy()}
