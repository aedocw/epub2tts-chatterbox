import textwrap

import pytest

from epub2tts_chatterbox.check_book import check_book


def write(tmp_path, contents, name="mybook.txt"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")
    return str(p)


def problems_of(result):
    return " | ".join(result.problems)


def test_a_well_formed_book_reports_no_problems(tmp_path):
    src = write(tmp_path, """
        Title: My Book
        Author: Jane Doe

        # Chapter 1

        The system reads the document and produces a plan for the work ahead.

        # Chapter 2

        Each component then carries out the portion of that plan assigned to it.
        """)

    result = check_book(src)

    assert result.problems == []
    assert result.chapters == 2
    assert result.chunks > 0


def test_a_missing_title_or_author_is_reported(tmp_path):
    src = write(tmp_path, """
        # Chapter 1

        The system reads the document and produces a plan for the work ahead.
        """)

    result = check_book(src)

    assert "Title:" in problems_of(result)
    assert "Author:" in problems_of(result)


def test_duplicate_chapter_titles_are_reported(tmp_path):
    """Players cannot distinguish chapters that share a name."""
    src = write(tmp_path, """
        Title: My Book
        Author: Jane Doe

        # Summary

        The system reads the document and produces a plan for the work ahead.

        # Summary

        Each component then carries out the portion of that plan assigned to it.
        """)

    result = check_book(src)

    assert "duplicate" in problems_of(result).lower()


def test_an_oversized_chunk_is_reported(tmp_path):
    """Very long single sentences fail during generation, mid-run."""
    long_sentence = " ".join(["word"] * 250) + "."
    src = write(tmp_path, f"""
        Title: My Book
        Author: Jane Doe

        # Chapter 1

        {long_sentence}
        """)

    result = check_book(src)

    assert "over 100 words" in problems_of(result)


def test_front_and_back_matter_is_flagged(tmp_path):
    src = write(tmp_path, """
        Title: My Book
        Author: Jane Doe

        # Table of Contents

        Chapter one begins on page one and chapter two begins on page ten.

        # Index

        Aardvark, page four. Zebra, page ninety.

        # Chapter 1

        The system reads the document and produces a plan for the work ahead.
        """)

    result = check_book(src)

    assert "front" in problems_of(result).lower() or "back" in problems_of(result).lower()


@pytest.mark.parametrize("title", ["1", "Section0001", "B31249 01", "blank"])
def test_unreadable_chapter_titles_are_flagged(tmp_path, title):
    src = write(tmp_path, f"""
        Title: My Book
        Author: Jane Doe

        # {title}

        The system reads the document and produces a plan for the work ahead.
        """)

    result = check_book(src)

    assert "readable" in problems_of(result).lower()


@pytest.mark.parametrize("title", ["Chapter 1", "Part 2: Foundations", "Appendix", "Preface"])
def test_ordinary_chapter_titles_are_not_flagged(tmp_path, title):
    """'Chapter 1' contains a digit but is perfectly readable."""
    src = write(tmp_path, f"""
        Title: My Book
        Author: Jane Doe

        # {title}

        The system reads the document and produces a plan for the work ahead.
        """)

    result = check_book(src)

    assert "readable" not in problems_of(result).lower()


def test_the_estimate_scales_with_the_number_of_chunks(tmp_path):
    src = write(tmp_path, """
        Title: My Book
        Author: Jane Doe

        # Chapter 1

        The system reads the document and produces a plan for the work ahead.
        """)

    result = check_book(src)

    assert result.estimate_hours == pytest.approx(result.chunks * 3.1 / 3600, rel=1e-6)
