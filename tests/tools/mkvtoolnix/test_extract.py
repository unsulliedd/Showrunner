from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from showrunner.tools.mkvtoolnix import extract as extracting
from showrunner.tools.mkvtoolnix.extract import ExtractError, extract_track
from showrunner.tools.process import ProcessCancelledError, ProgramNotFoundError, RunResult


class Program:
    """Stands in for mkvextract: remembers the command and answers with what it was given."""

    def __init__(self, returncode: int = 0, output: str = "", error: Exception | None = None) -> None:
        self.returncode, self.output, self.error = returncode, output, error
        self.command: tuple[str, ...] = ()

    def run(self, args: Any, *, on_line: Any = None, cancel: Any = None, **_: Any) -> RunResult:
        self.command = tuple(str(a) for a in args)
        if self.error is not None:
            raise self.error
        for line in self.output.splitlines():
            on_line(line)
        return RunResult(self.command, self.returncode, self.output, "")


def use(monkeypatch: pytest.MonkeyPatch, program: Program) -> None:
    monkeypatch.setattr(extracting, "run", program.run)


def test_a_track_is_extracted_by_its_id_to_the_output(monkeypatch: pytest.MonkeyPatch) -> None:
    program = Program()
    use(monkeypatch, program)
    extract_track(Path("mkvextract"), Path("video.mkv"), 3, Path("out.srt"))
    assert program.command == (
        "mkvextract",
        "--ui-language",
        "en",
        "--gui-mode",
        "tracks",
        "video.mkv",
        f"3:{Path('out.srt')}",
    )


def test_progress_is_the_fraction_the_program_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, Program(output="#GUI#begin_scanning_playlists\n#GUI#progress 25%\n#GUI#progress 100%\n"))
    seen: list[float] = []
    extract_track(Path("mkvextract"), Path("v.mkv"), 1, Path("o.sup"), progress=seen.append)
    assert seen == [0.25, 1.0]


def test_a_warning_is_not_a_failure_and_an_error_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, Program(returncode=1, output="#GUI#warning odd"))
    extract_track(Path("mkvextract"), Path("v.mkv"), 1, Path("o.srt"))
    use(monkeypatch, Program(returncode=2, output="#GUI#error The file is not a Matroska file\n"))
    with pytest.raises(ExtractError, match="not a Matroska file"):
        extract_track(Path("mkvextract"), Path("v.mkv"), 1, Path("o.srt"))
    use(monkeypatch, Program(returncode=2))
    with pytest.raises(ExtractError, match="exit code 2"):
        extract_track(Path("mkvextract"), Path("v.mkv"), 1, Path("o.srt"))


def test_a_missing_program_is_an_extract_error_and_a_cancel_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, Program(error=ProgramNotFoundError("gone", [])))
    with pytest.raises(ExtractError, match="gone"):
        extract_track(Path("mkvextract"), Path("v.mkv"), 1, Path("o.srt"))
    use(monkeypatch, Program(error=ProcessCancelledError("cancelled", [])))
    with pytest.raises(ProcessCancelledError):
        extract_track(Path("mkvextract"), Path("v.mkv"), 1, Path("o.srt"), cancel=threading.Event())
