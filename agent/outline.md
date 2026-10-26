# epub2tts-chatterbox — Repository Outline

> Reference document for building a Web frontend wrapper around `epub2tts-chatterbox`.
> All info below is derived from the repo as of the clone in `/workspace/repos/epub2tts-chatterbox`.
>
> 👉 **For the target system design (single GPU container, job lifecycle, FastAPI, progress,
> SSH-based dev flow) see [`architecture.md`](./architecture.md).** This file is the
> repository reference; `architecture.md` is the design.

## 1. What this project does

Free, open-source Python app that turns an **EPUB** (or plain text) into a full-featured **M4B audiobook** using [Chatterbox](https://github.com/resemble-ai/chatterbox) voice-cloning TTS.

Key features:
- Creates standard M4B audiobook file (AAC in MP4 container with embedded chapter metadata + cover art)
- Automatic chapter break detection (from EPUB TOC / headings / CSS classes / fallback)
- Embeds cover art (extracted from EPUB or user-supplied)
- **Resumes where it left off if interrupted** (checkpoints per chapter/paragraph as FLAC)
- EPUB must be **DRM-free**
- Requires **CUDA GPU** or **Apple Silicon (MPS)**; CPU falls back but is slow

## 1a. Development container + SSH flow (working branch `container`)

> Design shift: **one GPU container** holds everything. The agent develops **over SSH**
> into that container — **no docker socket is ever given to the agent.** The server and
> frontend are the same FastAPI app; each TTS job is a **subprocess** in its job dir.

- **`Dockerfile-dev`** — copy of `Dockerfile` that additionally installs `openssh-server`,
  enables root SSH login (`PermitRootLogin yes`, password `epub2tts` for dev, or mount your
  `authorized_keys`), `EXPOSE 22`, and uses `ENTRYPOINT ["/app/entrypoint-dev.sh"]`.
- **`entrypoint-dev.sh`** — starts `sshd`, creates `/data/{books,samples,jobs}`, keeps the
  container alive with `tail -f /dev/null`. Nothing auto-runs; you SSH in and drive it.
- **Build/run (manual):**
  ```
  sudo docker build -f Dockerfile-dev -t epub2tts-chatterbox-dev .
  sudo docker run -d --name epub2tts-chatterbox-dev \
    --gpus all \
    -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    -e HF_HOME=/root/.cache/huggingface \
    -v /mnt/models/epub2tts:/root/.cache/huggingface \
    -v /mnt/dm5/_ebook:/data \
    -p 2222:22 \
    epub2tts-chatterbox-dev
  # then:  ssh -p 2222 root@<host>   (password: epub2tts)
  ```
- **In-container dev:** code lives in `/app` (git checkout); `pip install -e .` for edits,
  run the FastAPI server, tail logs — all over SSH.

## 2. Repository layout

```
epub2tts-chatterbox/
├── README.md
├── Dockerfile                 # pytorch:2.1.2-cuda12.1 base, installs ffmpeg + espeak-ng
├── Dockerfile-dev             # dev image: + openssh-server, ENTRYPOINT entrypoint-dev.sh
├── entrypoint-dev.sh          # starts sshd, keeps container alive (SSH dev flow)
├── requirements.txt
├── setup.py                   # console script: epub2tts-chatterbox
├── epub2tts_chatterbox/
│   ├── __init__.py            # from .epub2tts_chatterbox import main
│   ├── epub2tts_chatterbox.py # MAIN SCRIPT (CLI, TTS pipeline)
│   └── epub_export.py         # Reusable EPUB→text/cover extraction library
└── agent/                     # THIS folder (outline.md, architecture.md,
                               #   development_environment.md, progress.md)
```

## 3. Dependencies & environment

- **Python 3.12** required (README says 3.12; Mac section oddly says <3.12 — use 3.12/3.11)
- `requirements.txt`: beautifulsoup4, ebooklib, **chatterbox-tts**, lxml, mutagen, nltk, numpy, pillow, pydub, setuptools, soundfile, tqdm
- **System deps**: `ffmpeg`, `espeak-ng` (chatterbox needs espeak), mecab (mac)
- **NLTK** `punkt`/`punkt_tab` tokenizers auto-download on first run (~50 MB); location controllable via env var `NLTK_DATA`
- **Chatterbox model** downloads from HuggingFace on first `ChatterboxTTS.from_pretrained()` (~GBs, cached in `HF_HOME`)
- **Docker**: base `pytorch/pytorch:2.1.2-cuda12.1-cudnn8-runtime`, run with `--gpus all`, mount books to `/data`, models to `/root/.cache/huggingface`

## 4. CLI usage (the main script)

Entry point: `epub2tts-chatterbox` (console script) → `epub2tts_chatterbox.epub2tts_chatterbox:main()`

### Arguments

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `sourcefile` | str (positional, required) | — | `.epub` **or** `.txt` file to process |
| `--sample` | str | `none` | Speaker sample for voice cloning (WAV/MP3, ideally 30–60 s, clean audio). Omitting → Chatterbox's default voice |
| `--cover` | str | — | Cover image (jpg/png) to embed in M4B |
| `--notitles` | flag | off | Don't read chapter titles aloud |
| `--exaggeration` | float | `0.7` | Chatterbox voice-cloning exaggeration factor |
| `--cfg_weight` | float | `0.4` | Chatterbox CFG weight |
| `--naming` | choice | `auto` | Chapter naming for EPUB: `auto`, `toc`, `heading`, `class`, `fallback` |

### Two-phase workflow

**Phase 1 — EPUB → text (exits after this; no TTS):**
```
epub2tts-chatterbox mybook.epub
```
- Uses `epub_export.export()` → writes `mybook.txt` (and `mybook.png` if a cover was found)
- In `--naming auto` mode with ambiguous chapters it prints an **interactive preview** and asks the user to pick a naming method (reads stdin!)
- Then `sys.exit()` — user must edit the `.txt`

**Phase 2 — text → audiobook:**
```
epub2tts-chatterbox mybook.txt --cover mybook.png --sample speaker.wav
```

## 5. Required text-file format (Phase 2 input)

`validate_text_file()` enforces this — the script **exits with error** if any part is missing:

```
Title: My Book
Author: John Doe

# Chapter 1
Some paragraph text...

# Chapter 2
More text...
```

Rules:
- Line 1 (optional but required to pass validation): `Title: <name>`
- Line 2: `Author: <name>`
- Chapter breaks: lines starting with `#` (rest of line = chapter title). Title lines with no alphanumerics count as `blank`.
- All other non-empty lines become paragraphs (sentence-tokenized by NLTK)
- **User is expected to edit the txt** to remove TOC/front matter and rename chapters
- Without a `#` line, everything before the first `#` becomes a `blank`-titled chapter

## 6. Output & intermediate files (all in CWD!)

⚠️ **Everything is written to the current working directory**, not next to the source file (except the Phase-1 txt/png which go next to the epub).

During Phase 2 (per chapter `part<i>.flac`):
- `part1.flac`, `part2.flac`, … — one FLAC per chapter (resume checkpoint: existing part = chapter skipped)
- `pgraphs<i>.flac` — per-paragraph intermediates (deleted after merge)
- `sntnc<i>.wav` — per-sentence Chatterbox output (deleted after merge)

Final:
- `FFMETADATAFILE` — temporary FFmpeg metadata (deleted)
- `filelist.txt` — temporary concat list (deleted)
- `mybook.m4a` — intermediate FLAC-in-MP4 (deleted)
- **`mybook (<speaker_name>).m4b`** — FINAL OUTPUT (`.txt` stripped, speaker = sample filename stem)
  - AAC audio + `[CHAPTER]` metadata (title, start/end, TIMEBASE 1/1000) + `covr` cover atom if `--cover` given

Pause timing: 600 ms between paragraphs, 2000 ms between chapters (hardcoded in `append_silence` calls).

## 7. Pipeline internals (useful for a Web UI)

`main()` flow for a `.txt`:
1. `ensure_punkt()` — download NLTK tokenizers
2. `get_book(sourcefile)` → `(book_contents, title, author, chapter_titles)`
   - `book_contents` = list of `{"title": str, "paragraphs": [str]}`
3. `validate_text_file(...)` — exits on missing Title/Author/`#`
4. `read_book(book_contents, sample, notitles, exaggeration, cfg_weight)`:
   - Device auto-detect: `cuda` → `mps` → `cpu`; `ChatterboxTTS.from_pretrained(device=...)`
   - Prints per-chapter **Elapsed / ETA** (chars-based estimate)
   - Prepend chapter title to first paragraph unless `--notitles` or title is `Title`/empty
   - `combine_short_paragraphs()` (< 6-word single-sentence paragraphs merged with next)
   - `combine_short_sentences()` (short sentences merged to ≥ 8 words)
   - Per sentence: `conditional_sentence_case()` (3 consecutive ALL-CAPS words → lowercase) then `model.generate()` with `torch.inference_mode` + bf16 autocast; 3 retry attempts
   - tqdm progress bar per chapter (sentence count); per-paragraph resume via existing `pgraphs<i>.flac`
   - Returns list of `part<i>.flac`
5. `generate_metadata(files, author, title, chapter_titles)` → `FFMETADATAFILE`
6. `make_m4b(files, sourcefile, speaker)` → ffmpeg concat → `.m4a` → aac+metadata → `.m4b`, cleans intermediates
7. `add_cover(cover, m4b)` → mutagen `mp4` `covr` atom

**Resume behavior:** killing the process mid-run is safe — `partN.flac` and `pgraphsN.flac` files are checked and skipped on next run.

## 8. `epub_export.py` — the reusable library (key for the Web frontend!)

This module is designed to be imported standalone:

```python
from epub2tts_chatterbox.epub_export import export_epub_to_dict, export_epub

# In-memory (no file written) — BEST for a web backend
book_data = export_epub_to_dict('book.epub', naming_method='auto',
                                verbose=False, interactive=False)
# -> {
#      'title': str,
#      'author': str,
#      'cover_image': PIL.Image | None,
#      'chapters': [{'title': str, 'paragraphs': [str], 'text': str}, ...]
#    }

# Or write the .txt (+ .png cover)
chapters = export_epub('book.epub', 'book.txt', naming_method='toc')
```

Other useful functions:
- `get_epub_cover(epub_path)` → file-like cover or `None`
- `build_toc_map(toc)` → `{filename: toc_title}`
- `get_chapter_titles_by_method(chap, item_name, item_id, toc_map)` → all 4 naming candidates at once
- `clean_text(text)` → normalizes whitespace/quotes/em-dashes
- `export(book, sourcefile, naming_method)` — legacy wrapper used by the CLI

`interactive=False` + explicit `naming_method` = **non-blocking**, which is exactly what a Web API needs (the CLI's `auto` mode prompts on stdin).

## 9. Gotchas / notes for the Web frontend

- **CWD-dependent output**: `read_book`/`make_m4b` write `partN.flac` etc. to CWD. A web backend must `os.chdir()` into a per-job temp dir (or refactor to accept an output dir).
- **Blocking + long-running**: TTS is minutes-to-hours; run it as a background job/worker, not a sync request. Poll status; the per-chapter `partN.flac` existence is a natural progress indicator.
- **Interactive stdin**: avoid in web context — always pass explicit `naming_method`, `interactive=False`, `verbose=False`. Also `check_for_file()` uses `input()` but is currently **not called** in `main()` (dead code — safe).
- **GPU required in practice**: model load `ChatterboxTTS.from_pretrained()` happens once per run; a long-lived worker should load it once and reuse it (the script doesn't).
- **Resume**: rerunning on the same CWD resumes; keep the job's working dir persistent.
- **Validation**: replicate `validate_text_file` server-side; the text must start with `Title:`/`Author:` and contain ≥1 `#` line.
- **Metadata naming**: final filename is `base (<sample-stem>).m4b`; `--notitles` and pauses (600/2000 ms) are hardcoded.
- **Sample audio**: 30–60 s clean WAV/MP3 recommended.

## 10. Suggested Web-frontend integration sketch

```
POST /jobs {epub_file, sample_file?, cover_file?, naming?, notitles?, exaggeration?, cfg_weight?}
  1. create job dir /data/jobs/<id>
  2. export_epub_to_dict(epub, naming_method=naming, verbose=False, interactive=False)
  3. build <job>/book.txt from the dict (Title/Author/# chapters)  [+ cover.png]
  4. enqueue worker:
       chdir(<job dir>); run main() args (or call read_book/generate_metadata/make_m4b/add_cover directly with a shared loaded model)
GET /jobs/{id}        → status: extracting | transcribing (chapter x/y, sentence i/n) | done
GET /jobs/{id}/audio  → stream/download the .m4b
```
Progress can be parsed from stdout (tqdm/ETA lines) or by inspecting `partN.flac` / `pgraphsN.flac` counts in the job dir.
