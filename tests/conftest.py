import pytest

from epub2tts_chatterbox.epub2tts_chatterbox import ensure_punkt


@pytest.fixture(scope="session", autouse=True)
def nltk_punkt():
    """get_book() tokenizes sentences, so the punkt data must be present.

    main() normally does this before parsing; tests need the same guarantee.
    """
    ensure_punkt()
