import textwrap

import pytest

from epub2tts_chatterbox.epub2tts_chatterbox import get_book


def write_book(tmp_path, contents):
    sourcefile = tmp_path / "mybook.txt"
    sourcefile.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")
    return str(sourcefile)


def test_chapter_titles_align_with_chapters_when_a_heading_has_no_content(tmp_path):
    """A heading left behind after deleting its body must not shift chapter labels.

    Deleting front matter (table of contents, copyright page) while leaving its
    '#' heading is the common editing mistake. Every audio part after it used to
    be labeled with the previous chapter's title in the finished m4b.
    """
    sourcefile = write_book(
        tmp_path,
        """
        Title: My Book
        Author: Jane Doe
        # Table of Contents
        # Chapter One
        It was a dark and stormy night.
        # Chapter Two
        The rain continued until morning.
        """,
    )

    book_contents, _, _, chapter_titles = get_book(sourcefile)

    assert [c["title"] for c in book_contents] == ["Chapter One", "Chapter Two"]
    assert chapter_titles == ["Chapter One", "Chapter Two"]


def test_chapter_titles_align_when_trailing_heading_has_no_content(tmp_path):
    """A trailing heading with no body produces no audio part, so it gets no label."""
    sourcefile = write_book(
        tmp_path,
        """
        Title: My Book
        Author: Jane Doe
        # Chapter One
        It was a dark and stormy night.
        # Acknowledgements
        """,
    )

    book_contents, _, _, chapter_titles = get_book(sourcefile)

    assert [c["title"] for c in book_contents] == ["Chapter One"]
    assert chapter_titles == ["Chapter One"]


def test_well_formed_book_is_unchanged(tmp_path):
    """The ordinary case must keep working exactly as before."""
    sourcefile = write_book(
        tmp_path,
        """
        Title: My Book
        Author: Jane Doe
        # Chapter One
        It was a dark and stormy night.
        # Chapter Two
        The rain continued until morning.
        """,
    )

    book_contents, book_title, book_author, chapter_titles = get_book(sourcefile)

    assert book_title == "My Book"
    assert book_author == "Jane Doe"
    assert chapter_titles == ["Chapter One", "Chapter Two"]
    assert book_contents[0]["paragraphs"] == ["It was a dark and stormy night."]
    assert book_contents[1]["paragraphs"] == ["The rain continued until morning."]


def test_text_before_first_heading_is_kept_as_a_blank_titled_chapter(tmp_path):
    """Content preceding any '#' still becomes a chapter, labeled 'blank'."""
    sourcefile = write_book(
        tmp_path,
        """
        Title: My Book
        Author: Jane Doe
        Some stray preamble text.
        # Chapter One
        It was a dark and stormy night.
        """,
    )

    book_contents, _, _, chapter_titles = get_book(sourcefile)

    assert [c["title"] for c in book_contents] == ["blank", "Chapter One"]
    assert chapter_titles == ["blank", "Chapter One"]


def test_non_alphanumeric_heading_is_labeled_blank(tmp_path):
    """A heading like '# ---' has no readable name and falls back to 'blank'."""
    sourcefile = write_book(
        tmp_path,
        """
        Title: My Book
        Author: Jane Doe
        # ---
        It was a dark and stormy night.
        """,
    )

    book_contents, _, _, chapter_titles = get_book(sourcefile)

    assert [c["title"] for c in book_contents] == ["blank"]
    assert chapter_titles == ["blank"]
