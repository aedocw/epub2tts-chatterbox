"""
Job state management — files are the database.

Each job is a directory under the data root's ``jobs/`` folder containing a
``state.json`` that is the single source of truth for that job.
"""

import json
import os
import re
import tempfile
import time
from typing import Optional

# Job states
DRAFT = "DRAFT"
AWAITING_REVIEW = "AWAITING_REVIEW"
TRANSCRIBING = "TRANSCRIBING"
ENCODING = "ENCODING"
DONE = "DONE"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

ACTIVE_STATES = {DRAFT, AWAITING_REVIEW, TRANSCRIBING, ENCODING}
TERMINAL_STATES = {DONE, CANCELLED}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:60] or "book"


def make_job_id(book_title: str) -> str:
    """<book-title-slug>-<YYYYMMDD-HHMM>"""
    return f"{_slugify(book_title)}-{time.strftime('%Y%m%d-%H%M')}"


def jobs_root(data_root: str) -> str:
    return os.path.join(data_root, "jobs")


def job_dir(data_root: str, job_id: str) -> str:
    # job ids are slugs we generated — never contain path separators
    safe = os.path.basename(job_id)
    return os.path.join(jobs_root(data_root), safe)


def state_path(data_root: str, job_id: str) -> str:
    return os.path.join(job_dir(data_root, job_id), "state.json")


def progress_path(data_root: str, job_id: str) -> str:
    return os.path.join(job_dir(data_root, job_id), "progress.json")


def _atomic_write(path: str, data: dict):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def read_state(data_root: str, job_id: str) -> Optional[dict]:
    path = state_path(data_root, job_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_state(data_root: str, state: dict):
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write(state_path(data_root, state["id"]), state)


def set_job_state(data_root: str, job_id: str, new_state: str, **fields):
    """Update a job's state (and optional extra fields). Returns new state."""
    state = read_state(data_root, job_id)
    if state is None:
        raise FileNotFoundError(f"job {job_id!r} not found")
    state["state"] = new_state
    for key, value in fields.items():
        state[key] = value
    write_state(data_root, state)
    return state


def write_progress(data_root: str, job_id: str, progress: dict):
    _atomic_write(progress_path(data_root, job_id), progress)


def read_progress(data_root: str, job_id: str) -> Optional[dict]:
    path = progress_path(data_root, job_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def list_jobs(data_root: str) -> list[dict]:
    """All jobs, newest first. Each entry is the full state dict."""
    root = jobs_root(data_root)
    jobs = []
    if not os.path.isdir(root):
        return jobs
    for name in os.listdir(root):
        state = read_state(data_root, name)
        if state is not None:
            jobs.append(state)
    jobs.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return jobs


def create_job(data_root: str, state: dict):
    """Create the job dir + initial state.json."""
    jdir = job_dir(data_root, state["id"])
    os.makedirs(jdir, exist_ok=True)
    state["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write(os.path.join(jdir, "state.json"), state)
    return jdir


def find_output_m4b(jdir: str) -> Optional[str]:
    """The final .m4b file in a job dir, if any."""
    for name in sorted(os.listdir(jdir)):
        if name.lower().endswith(".m4b"):
            return os.path.join(jdir, name)
    return None


def build_book_txt(jdir: str, title: str, author: str, chapters: list[dict]):
    """Write book.txt in the exact format the CLI expects.

    Empty chapters are skipped — the CLI's get_book() drops chapters without
    paragraphs, and partN.flac numbering must stay aligned with chapter order.
    """
    lines = [f"Title: {title}", f"Author: {author}", ""]
    for chapter in chapters:
        if not chapter.get("paragraphs"):
            continue
        lines.append(f"# {chapter.get('title') or 'blank'}")
        lines.append("")
        for para in chapter["paragraphs"]:
            lines.append(para)
            lines.append("")
    path = os.path.join(jdir, "book.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
