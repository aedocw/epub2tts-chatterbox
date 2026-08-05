"""Validate an edited book text before spending hours converting it.

Reached with --check. Reports the structure of the text and flags the problems
that cause a conversion to fail or to produce an unusable audiobook: chunks too
long for the model, chapter titles that are duplicated or unreadable, and
sections such as an index or table of contents that should not be narrated.
"""
import re
from dataclasses import dataclass, field

from nltk.tokenize import sent_tokenize

# Sections that are noise as audio: navigation, indexes, advertising.
JUNK_MARKERS = (
    "index", "table of contents", "why subscribe", "other books",
    "join our discord", "free benefits", "download a free", "subscribe for a free",
)

# Measured on an M4 Pro; only used for a rough runtime estimate.
SECONDS_PER_CHUNK = 3.1

# Chatterbox degrades badly on very long inputs -- see upstream issue #7.
MAX_CHUNK_WORDS = 100


@dataclass
class CheckResult:
    title: str = ""
    author: str = ""
    chapters: int = 0
    words: int = 0
    chunks: int = 0
    largest_chunk: int = 0
    estimate_hours: float = 0.0
    problems: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.problems


def _is_unreadable(title):
    """A chapter title a listener could not make sense of in a player menu."""
    title = title.strip()
    if title.lower() in ("blank", "title"):
        return True
    if re.fullmatch(r"\d+", title):                    # a bare number
        return True
    if re.fullmatch(r"[A-Za-z]+\d+", title):           # Section0001
        return True
    return bool(re.match(r"^[A-Za-z]{1,3}\d{4,}\b", title))   # publisher code


def check_book(sourcefile):
    """Inspect an edited book text. Returns a CheckResult."""
    from epub2tts_chatterbox.epub2tts_chatterbox import (
        combine_short_paragraphs,
        combine_short_sentences,
        get_book,
    )

    book, title, author, titles = get_book(sourcefile)
    result = CheckResult(title=title, author=author, chapters=len(book))

    if title == sourcefile or title.endswith(".txt"):
        result.problems.append("No 'Title:' line at the top of the file")
    if author == "Unknown":
        result.problems.append("No 'Author:' line at the top of the file")

    if [c["title"] for c in book] != titles:
        result.problems.append("Chapter labels are not aligned with chapters")

    duplicates = len(titles) - len(set(titles))
    if duplicates:
        result.problems.append(
            f"{duplicates} duplicate chapter title(s) -- players cannot tell them apart")

    # Chunk exactly as the converter will, so the numbers match what it does.
    chunks = []
    for index, chapter in enumerate(book, 1):
        result.words += sum(len(p.split()) for p in chapter["paragraphs"])
        for paragraph in combine_short_paragraphs(chapter["paragraphs"]):
            for chunk in combine_short_sentences(sent_tokenize(paragraph)):
                chunks.append((len(chunk.split()), index, chapter["title"]))

    result.chunks = len(chunks)
    result.largest_chunk = max((c[0] for c in chunks), default=0)
    result.estimate_hours = result.chunks * SECONDS_PER_CHUNK / 3600

    oversized = sorted((c for c in chunks if c[0] > MAX_CHUNK_WORDS), reverse=True)
    if oversized:
        result.problems.append(
            f"{len(oversized)} chunk(s) over {MAX_CHUNK_WORDS} words -- these usually fail")
        for words, index, chapter_title in oversized[:5]:
            result.notes.append(f"    {words} words in chapter {index}: {chapter_title}")

    junk = [(i, t) for i, t in enumerate(titles, 1)
            if any(marker in t.lower() for marker in JUNK_MARKERS)]
    if junk:
        result.problems.append(
            f"{len(junk)} chapter(s) look like front or back matter, not content")
        for index, chapter_title in junk[:8]:
            result.notes.append(f"    chapter {index}: {chapter_title}")

    unreadable = [(i, t) for i, t in enumerate(titles, 1) if _is_unreadable(t)]
    if unreadable:
        result.problems.append(
            f"{len(unreadable)} chapter title(s) are not human readable")
        for index, chapter_title in unreadable[:8]:
            result.notes.append(f"    chapter {index}: {chapter_title!r}")

    return result


def report(result):
    """Print a CheckResult. Returns the exit status to use."""
    print(f"title    : {result.title}")
    print(f"author   : {result.author}")
    print(f"chapters : {result.chapters}")
    print(f"words    : {result.words:,}")
    print(f"chunks   : {result.chunks:,}  (largest {result.largest_chunk} words)")
    print(f"estimate : {result.estimate_hours:.1f} h")
    print()

    if result.ok:
        for note in result.notes:
            print(note)
        print("OK -- no problems found.")
        return 0

    print("PROBLEMS")
    for problem in result.problems:
        print(f"  - {problem}")
    if result.notes:
        print()
        for note in result.notes:
            print(note)
    print("\nFix these before converting.")
    return 1
