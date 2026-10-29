"""
Job supervisor — spawns ONE `epub2tts-chatterbox` CLI subprocess at a time.

Runs as a background task inside the FastAPI app (single worker).
- Enforces the single-job lock (1080 8 GB VRAM fits one Chatterbox instance).
- Tails the subprocess stdout (tqdm / "Chapter (i/N)" lines) into progress.json
  and mirrors a summary into state.json.
- On startup, orphaned TRANSCRIBING jobs (no live process) are marked FAILED
  ("interrupted — resumable"); the partN.flac checkpoints allow resume.
"""

import asyncio
import os
import re
import signal
import time
from typing import Optional

from . import state as st

_CHAPTER_RE = re.compile(r"Chapter \((\d+)/(\d+)\):")
_TQDM_RE = re.compile(r"(\d+)%(?:\|[^|]*\|)?\s*(\d+/\d+),\s*(\d+)it/s")
_SKIP_RE = re.compile(r"part(\d+)\.flac exists")


class JobProcess:
    """A running CLI subprocess + the latest parsed progress."""

    def __init__(self, proc: asyncio.subprocess.Process, job_id: str,
                 start_time: float, chapters_total: int):
        self.proc = proc
        self.job_id = job_id
        self.started_at = start_time
        self.chapters_total = chapters_total
        self.chapter = 0          # current chapter (1-based)
        self.sent_done = 0        # sentences done in current chapter
        self.sent_total = 0       # sentences in current chapter
        self.skipped = set()      # partN existing at start (already done)
        self.last_stdout = ""      # last non-empty stdout line (for UI)
        self._buffer = ""
        self._last_state_write = 0.0
        self.cancelled = False     # set True when cancel() is called

    def feed(self, data: str):
        self._buffer += data
        # process complete lines; keep the tail (tqdm \r fragments)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self.last_stdout = line
            m = _CHAPTER_RE.search(line)
            if m:
                self.chapter = int(m.group(1))
                self.sent_done = 0
                self.sent_total = 0
                continue
            m = _SKIP_RE.search(line)
            if m:
                self.skipped.add(int(m.group(1)))
                continue
            # tqdm progress fragments (may be partial, re-scan buffer tail too)
            m = _TQDM_RE.search(line)
            if m:
                self.sent_done = int(m.group(2).split("/")[0])
                self.sent_total = int(m.group(2).split("/")[1])

    @property
    def chapters_done(self) -> int:
        """Chapters fully finished (skip markers + chapters behind current)."""
        done = len(self.skipped)
        if self.chapter > 0:
            done = max(done, self.chapter - 1)
        return min(done, self.chapters_total)

    def progress_dict(self) -> dict:
        elapsed = time.time() - self.started_at
        total = self.chapters_total or 1
        # rough overall fraction: finished chapters + current chapter fraction
        frac_chapter = (self.sent_done / self.sent_total) if self.sent_total else 0.0
        frac = (self.chapters_done + frac_chapter) / total
        # ETA from overall rate
        eta = None
        if frac > 0.02:
            eta = int(elapsed * (1 - frac) / frac)
        return {
            "chapter": self.chapter,
            "chapters_total": self.chapters_total,
            "sentence": self.sent_done,
            "sentences_total": self.sent_total,
            "pct": round(min(frac, 1.0) * 100, 1),
            "elapsed_sec": int(elapsed),
            "eta_sec": eta,
            "last_stdout": self.last_stdout,
        }


class Supervisor:
    def __init__(self, data_root: str):
        self.data_root = data_root
        self.current: Optional[JobProcess] = None
        self._stop = False

    # ------------------------------------------------------------------ api
    def running_job_id(self) -> Optional[str]:
        if self.current is not None and self.current.proc.returncode is None:
            return self.current.job_id
        return None

    def is_busy(self) -> bool:
        return self.running_job_id() is not None

    def cancel(self, job_id: str):
        """Kill the subprocess for job_id if it is ours."""
        if self.current and self.current.job_id == job_id:
            self.current.cancelled = True
            try:
                self.current.proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    # ------------------------------------------------------------- internal
    def _chapters_total_for(self, job_id: str) -> int:
        state = st.read_state(self.data_root, job_id)
        if state:
            return len(state.get("book", {}).get("chapters", []))
        return 1

    async def _spawn(self, job_id: str):
        jdir = st.job_dir(self.data_root, job_id)
        book_txt = os.path.join(jdir, "book.txt")
        state = st.read_state(self.data_root, job_id) or {}
        params = state.get("params", {})
        sample = params.get("sample")
        cover = params.get("cover")

        # Resolve relative paths (e.g. "speaker/dii.wav") against DATA_ROOT
        if sample and not os.path.isabs(sample):
            sample = os.path.join(self.data_root, sample)
        if cover and not os.path.isabs(cover):
            # cover lives in the job dir
            cover = os.path.join(jdir, cover)

        args = [
            "/opt/conda/bin/python3", "-m",
            "epub2tts_chatterbox.epub2tts_chatterbox",
            "book.txt",
        ]
        if sample:
            args += ["--sample", sample]
        if cover:
            args += ["--cover", cover]
        if params.get("notitles"):
            args.append("--notitles")
        if params.get("exaggeration") is not None:
            args += ["--exaggeration", str(params["exaggeration"])]
        if params.get("cfg_weight") is not None:
            args += ["--cfg_weight", str(params["cfg_weight"])]

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=jdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self.current = JobProcess(proc, job_id, time.time(),
                                  self._chapters_total_for(job_id))
        st.set_job_state(self.data_root, job_id, st.TRANSCRIBING)
        return proc

    async def _finalize(self, jp: JobProcess):
        job_id = jp.job_id
        jdir = st.job_dir(self.data_root, job_id)
        rc = jp.proc.returncode
        state = st.read_state(self.data_root, job_id)
        if state is None:
            self.current = None
            return

        m4b = st.find_output_m4b(jdir)
        if rc == 0 and m4b:
            state["state"] = st.DONE
            state["progress"] = None
            state["output"] = {
                "path": os.path.basename(m4b),
                "size": os.path.getsize(m4b),
            }
            state["error"] = None
        elif jp.cancelled:
            state["state"] = st.CANCELLED
            state["progress"] = None
            state["error"] = "cancelled by user"
        else:
            state["state"] = st.FAILED
            tail = jp.last_stdout or f"process exited with code {rc}"
            state["error"] = tail
            err_path = os.path.join(jdir, "error.txt")
            try:
                with open(err_path, "a", encoding="utf-8") as f:
                    f.write(f"--- exit code {rc} ---\n{tail}\n")
            except OSError:
                pass
        st.write_state(self.data_root, state)
        self.current = None

    def _pick_next_job(self) -> Optional[str]:
        """Oldest job in TRANSCRIBING with no live process."""
        candidates = [s for s in st.list_jobs(self.data_root)
                      if s.get("state") == st.TRANSCRIBING]
        candidates.sort(key=lambda s: s.get("created_at", ""))
        for s in candidates:
            return s["id"]
        return None

    def mark_orphans_failed(self):
        """Startup: TRANSCRIBING jobs with no live process -> FAILED (resumable)."""
        for s in st.list_jobs(self.data_root):
            if s.get("state") == st.TRANSCRIBING:
                st.set_job_state(self.data_root, s["id"], st.FAILED,
                                 error="interrupted — resumable")

    # --------------------------------------------------------------- main loop
    async def run(self):
        self.mark_orphans_failed()
        while not self._stop:
            jp = self.current
            if jp is not None:
                if jp.proc.returncode is None:
                    try:
                        await self._pump_once(jp)
                    except (StopAsyncIteration, asyncio.CancelledError):
                        pass
                    if jp.proc.returncode is not None:
                        # drain whatever stdout is left
                        try:
                            while True:
                                line = await jp.proc.stdout.readline()
                                if not line:
                                    break
                                jp.feed(line.decode("utf-8", errors="replace"))
                                self._log(jp, line)
                        except Exception:
                            pass
                        await self._finalize(jp)
                continue
            # no job running — pick the next queued one
            job_id = self._pick_next_job()
            if job_id:
                try:
                    await self._spawn(job_id)
                except Exception as e:
                    st.set_job_state(self.data_root, job_id, st.FAILED,
                                     error=f"spawn failed: {e}")
            else:
                await asyncio.sleep(2)

    def _log(self, jp: JobProcess, raw: bytes):
        log_path = os.path.join(st.job_dir(self.data_root, jp.job_id),
                                "stdout.log")
        try:
            with open(log_path, "ab") as f:
                f.write(raw)
        except OSError:
            pass

    async def _pump_once(self, jp: JobProcess):
        """Read one chunk of stdout (raises StopAsyncIteration on EOF)."""
        line = await jp.proc.stdout.readline()
        if not line:
            # stdout hit EOF — wait for the process to exit so returncode is set
            await jp.proc.wait()
            raise StopAsyncIteration
        jp.feed(line.decode("utf-8", errors="replace"))
        self._log(jp, line)
        st.write_progress(self.data_root, jp.job_id, jp.progress_dict())
        # throttle state.json mirrors (tqdm emits many lines/sec)
        now = time.time()
        if now - jp._last_state_write >= 2.0:
            jp._last_state_write = now
            state = st.read_state(self.data_root, jp.job_id)
            if state is not None:
                state["progress"] = jp.progress_dict()
                st.write_state(self.data_root, state)

    async def stop(self):
        self._stop = True
        if self.current and self.current.proc.returncode is None:
            try:
                self.current.proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
