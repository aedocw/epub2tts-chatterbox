import os
import subprocess

import pytest

from epub2tts_chatterbox import epub2tts_chatterbox as m


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A working directory holding the per-chapter parts and the metadata file."""
    monkeypatch.chdir(tmp_path)
    for name in ["part1.flac", "part2.flac", "FFMETADATAFILE"]:
        (tmp_path / name).write_text("pretend audio")
    return tmp_path


def fake_ffmpeg(outputm4a, fail_on_call, make_outputs=True):
    """Stand in for ffmpeg: succeed until fail_on_call, then return non-zero."""
    calls = {"n": 0}

    def run(cmd, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            return subprocess.CompletedProcess(cmd, 1)
        if make_outputs:
            open(cmd[-1], "w").write("output")
        return subprocess.CompletedProcess(cmd, 0)

    run.calls = calls
    return run


def test_parts_are_kept_when_the_final_mux_fails(run_dir, monkeypatch):
    """Losing every chapter part because ffmpeg failed destroys hours of TTS output.

    The concat step succeeds and writes the intermediate .m4a, then the m4b mux
    fails. The parts are the only copy of the generated audio, so they must
    survive for the run to be resumable.
    """
    monkeypatch.setattr(m.subprocess, "run", fake_ffmpeg("mybook.m4a", fail_on_call=2))

    with pytest.raises(RuntimeError):
        m.make_m4b(["part1.flac", "part2.flac"], "mybook.txt", "george.wav")

    assert os.path.isfile("part1.flac")
    assert os.path.isfile("part2.flac")


def test_parts_are_kept_when_the_concat_fails(run_dir, monkeypatch):
    """Same guarantee when ffmpeg fails at the first step instead of the second."""
    monkeypatch.setattr(m.subprocess, "run", fake_ffmpeg("mybook.m4a", fail_on_call=1))

    with pytest.raises(RuntimeError):
        m.make_m4b(["part1.flac", "part2.flac"], "mybook.txt", "george.wav")

    assert os.path.isfile("part1.flac")
    assert os.path.isfile("part2.flac")


def test_successful_mux_cleans_up_and_returns_the_m4b(run_dir, monkeypatch):
    """The normal path still removes scratch files and reports the output name."""
    monkeypatch.setattr(m.subprocess, "run", fake_ffmpeg("mybook.m4a", fail_on_call=0))

    out = m.make_m4b(["part1.flac", "part2.flac"], "mybook.txt", "george.wav")

    assert out == "mybook (george).m4b"
    assert os.path.isfile(out)
    assert not os.path.isfile("part1.flac")
    assert not os.path.isfile("filelist.txt")
    assert not os.path.isfile("FFMETADATAFILE")


def test_output_name_uses_the_extension_not_every_occurrence(run_dir, monkeypatch):
    """'.txt' appearing in a parent directory must not be stripped from the path."""
    monkeypatch.setattr(m.subprocess, "run", fake_ffmpeg("x.m4a", fail_on_call=0))
    booksdir = run_dir / ".txtfiles"
    booksdir.mkdir()
    sourcefile = str(booksdir / "mybook.txt")

    out = m.make_m4b(["part1.flac"], sourcefile, "george.wav")

    assert out == str(booksdir / "mybook (george).m4b")
