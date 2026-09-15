import pytest

from epub2tts_chatterbox import epub2tts_chatterbox as m


class FailingModel:
    """Model whose generate() always fails, as MPS does when it runs out of memory."""

    sr = 24000
    device = "cpu"

    def generate(self, text, **kwargs):
        raise RuntimeError("MPS backend out of memory")


class WorkingModel:
    sr = 24000
    device = "cpu"

    def __init__(self):
        self.generated = []

    def generate(self, text, **kwargs):
        self.generated.append(text)
        return object()


@pytest.fixture(autouse=True)
def stub_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m.ta, "save", lambda path, wav, sr: open(path, "w").write("wav"))


def test_a_sentence_that_never_succeeds_raises():
    """Giving up silently left no audio file, and the caller then exited with status 0.

    A whole multi-hour run would end reporting success.
    """
    with pytest.raises(RuntimeError):
        m.chatterbox_read(["This sentence cannot be generated."], "none",
                          ["sntnc0.wav"], FailingModel(), 0.7, 0.4)


def test_the_error_identifies_the_sentence():
    with pytest.raises(RuntimeError, match="cannot be generated"):
        m.chatterbox_read(["This sentence cannot be generated."], "none",
                          ["sntnc0.wav"], FailingModel(), 0.7, 0.4)


def test_working_sentences_are_unaffected():
    model = WorkingModel()
    sentences = ["One sentence.", "Two sentence."]

    m.chatterbox_read(sentences, "none", ["sntnc0.wav", "sntnc1.wav"], model, 0.7, 0.4)

    assert model.generated == sentences
