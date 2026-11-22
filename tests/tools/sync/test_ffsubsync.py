"""The ffsubsync adapter and its worker, with a stand-in for ffsubsync's own module in the child process; and one run of
the real library on subtitles alone, which needs no program."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.tools.process import ProcessCancelledError
from showrunner.tools.sync import ENGINES, FfsubsyncAdapter, SyncError, SyncRequest

FAKE = Path(__file__).parent / "fake_ffsubsync"
FFMPEG = Path("ffmpeg-stand-in")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The folder the stand-in writes the arguments it got to."""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(FAKE), os.environ.get("PYTHONPATH", "")])))
    arguments = tmp_path / "arguments.txt"
    monkeypatch.setenv("FAKE_ARGS", str(arguments))
    return arguments


def request(
    tmp_path: Path,
    reference: Path | None = None,
    settings: dict[str, str] | None = None,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> SyncRequest:
    subtitle = tmp_path / "in.srt"
    write_cues(subtitle, [Cue(1.0, 3.0, "one"), Cue(1000.0, 1010.0, "two")])
    return SyncRequest(
        subtitle, tmp_path / "video.mkv", reference, tmp_path / "out.srt", settings or {}, None, progress, cancel
    )


def test_the_outcome_is_normalised_by_the_length_of_the_subtitle(fake: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_SCORE", "50500")  # half of the 1010 s at 100 samples a second
    monkeypatch.setenv("FAKE_OFFSET", "-2.5")
    seen: list[float] = []
    outcome = FfsubsyncAdapter(FFMPEG).sync(request(tmp_path, progress=seen.append))
    assert (outcome.offset, outcome.scale, outcome.unsure, outcome.length) == (-2.5, 1.0, False, 1010.0)
    assert outcome.score == pytest.approx(0.5)
    assert seen == [0.25, 0.5, 1.0]
    assert read_cues(tmp_path / "out.srt") == read_cues(tmp_path / "in.srt")


def test_the_shift_is_the_largest_a_line_is_moved_by(fake: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_OFFSET", "0.1")
    monkeypatch.setenv("FAKE_SCALE", "1.001")
    outcome = FfsubsyncAdapter(FFMPEG).sync(request(tmp_path))
    assert outcome.shift == pytest.approx(0.1 + 0.001 * 1010)


def test_the_engines_own_doubt_is_reported(fake: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "unsure")
    assert FfsubsyncAdapter(FFMPEG).sync(request(tmp_path)).unsure


def test_the_audio_is_listened_to_and_the_settings_are_passed(fake: Path, tmp_path: Path) -> None:
    given = request(tmp_path, settings={"max_offset": "30", "framerate": "off"})
    FfsubsyncAdapter(FFMPEG).sync(given)
    arguments = fake.read_text(encoding="utf-8").splitlines()
    assert arguments[0] == str(given.video)
    assert arguments[arguments.index("--vad") + 1] == "webrtc"
    assert arguments[arguments.index("--max-offset-seconds") + 1] == "30"
    assert "--no-fix-framerate" in arguments
    assert arguments[arguments.index("--ffmpeg-path") + 1] == str(FFMPEG)
    assert arguments[arguments.index("--encoding") + 1] == "utf-8"


def test_a_reference_subtitle_needs_no_voice_detector_nor_ffmpeg(fake: Path, tmp_path: Path) -> None:
    reference = tmp_path / "reference.srt"
    FfsubsyncAdapter().sync(request(tmp_path, reference))
    arguments = fake.read_text(encoding="utf-8").splitlines()
    assert arguments[0] == str(reference)
    assert "--vad" not in arguments
    assert "--ffmpeg-path" not in arguments


def test_the_audio_without_ffmpeg_is_refused(fake: Path, tmp_path: Path) -> None:
    adapter = FfsubsyncAdapter()
    assert not adapter.audio
    with pytest.raises(SyncError, match="ffmpeg"):
        adapter.sync(request(tmp_path))


def test_a_failure_says_why(fake: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "refuse")
    with pytest.raises(SyncError, match="no speech in the reference"):
        FfsubsyncAdapter(FFMPEG).sync(request(tmp_path))


def test_cancel_stops_the_child_process(fake: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "slow")
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    with pytest.raises(ProcessCancelledError):
        FfsubsyncAdapter(FFMPEG).sync(request(tmp_path, cancel=cancel))


def test_the_engines_are_found_by_name() -> None:
    assert {"ffsubsync": FfsubsyncAdapter} == ENGINES
    assert {setting.key for setting in FfsubsyncAdapter.settings} == {"max_offset", "framerate", "vad"}
    assert set(FfsubsyncAdapter.defaults) == {"in_sync_below", "unsure_below"}


@pytest.mark.skipif(not FfsubsyncAdapter.available(), reason="ffsubsync is not installed")
def test_the_real_library_finds_the_shift_between_two_subtitles(tmp_path: Path) -> None:
    lines = [Cue(float(start), start + 2.0, "x") for start in (5, 12, 14, 30, 41, 47, 63, 80, 82, 95, 110, 118, 130)]
    reference, moved = tmp_path / "reference.srt", tmp_path / "moved.srt"
    write_cues(reference, lines)
    write_cues(moved, [Cue(c.start + 2.0, c.end + 2.0, c.text) for c in lines])
    outcome = FfsubsyncAdapter().sync(
        SyncRequest(moved, tmp_path / "video.mkv", reference, tmp_path / "out.srt", {"framerate": "off"}, None)
    )
    assert outcome.offset == pytest.approx(-2.0, abs=0.05)
    assert outcome.score > 0.9
    assert read_cues(tmp_path / "out.srt")[0].start == pytest.approx(5.0, abs=0.05)
