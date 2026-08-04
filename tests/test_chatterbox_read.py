import pytest

from epub2tts_chatterbox import epub2tts_chatterbox as m


class FakeModel:
    """Minimal stand-in for ChatterboxTTS: records generate calls, no audio."""

    sr = 24000

    def __init__(self, device):
        self.device = device
        self.generated = []

    def generate(self, text, **kwargs):
        self.generated.append(text)
        return object()


@pytest.fixture
def stub_audio(tmp_path, monkeypatch):
    """Make ta.save write a real file so chatterbox_read's existence check passes."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(m.ta, "save", lambda path, wav, sr: open(path, "w").write("wav"))


def count_empty_cache_calls(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(m.torch.mps, "empty_cache", lambda: calls.__setitem__("n", calls["n"] + 1))
    return calls


def test_mps_allocator_is_released_after_each_sentence(stub_audio, monkeypatch):
    """Without this the MPS cache grows unbounded and the OS kills the process.

    The growth never shows up in RSS, so nothing else in the pipeline catches it.
    """
    calls = count_empty_cache_calls(monkeypatch)
    model = FakeModel("mps")
    sentences = ["One sentence.", "Two sentence.", "Three sentence."]
    filenames = [f"sntnc{i}.wav" for i in range(len(sentences))]

    m.chatterbox_read(sentences, "none", filenames, model, 0.7, 0.4)

    assert calls["n"] == len(sentences)


def test_allocator_is_not_touched_on_other_devices(stub_audio, monkeypatch):
    """CPU and CUDA have their own allocator behaviour; leave them alone."""
    calls = count_empty_cache_calls(monkeypatch)
    model = FakeModel("cpu")
    sentences = ["One sentence.", "Two sentence."]
    filenames = [f"sntnc{i}.wav" for i in range(len(sentences))]

    m.chatterbox_read(sentences, "none", filenames, model, 0.7, 0.4)

    assert calls["n"] == 0


def test_every_sentence_is_still_generated(stub_audio, monkeypatch):
    """The cache release must not disturb normal generation."""
    count_empty_cache_calls(monkeypatch)
    model = FakeModel("mps")
    sentences = ["One sentence.", "Two sentence.", "Three sentence."]
    filenames = [f"sntnc{i}.wav" for i in range(len(sentences))]

    m.chatterbox_read(sentences, "none", filenames, model, 0.7, 0.4)

    assert model.generated == sentences
