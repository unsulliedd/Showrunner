"""The engines that read a subtitle out of the video, with stand-ins for mkvextract and Tesseract."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.subtitles import Step, StepKind
from showrunner.stages.subtitles import read as reading
from showrunner.stages.subtitles.read import ocr_runner, read_runner, track_cues
from showrunner.stages.subtitles.work import StepWork
from showrunner.tools.cleanit import OCR_EXTRA, RuleBook, RuleDef, RuleSet, builtin_sets
from showrunner.tools.mkvtoolnix.extract import ExtractError

ENGLISH = Language("eng")
SRT = Track(2, TrackKind.SUBTITLE, "S_TEXT/UTF8", ENGLISH, subtitle=SubtitleProperties())
ASS = Track(3, TrackKind.SUBTITLE, "S_TEXT/ASS", ENGLISH, subtitle=SubtitleProperties())
PGS = Track(4, TrackKind.SUBTITLE, "S_HDMV/PGS", ENGLISH, subtitle=SubtitleProperties(text_based=False))


class Extractor:
    """Stands in for mkvextract: writes what it was given to the output and remembers the track asked for."""

    def __init__(self, cues: list[Cue] | None = None, error: str = "") -> None:
        self.cues = cues or [Cue(1, 2, "Hello"), Cue(3, 4, "Hte end")]
        self.error = error
        self.asked: list[tuple[int, str]] = []

    def __call__(
        self,
        mkvextract: Path,
        video: Path,
        track_id: int,
        output: Path,
        *,
        progress: Any = None,
        cancel: Any = None,
    ) -> None:
        self.asked.append((track_id, output.suffix))
        if self.error:
            raise ExtractError(self.error)
        if output.suffix == ".sup":
            output.write_bytes(b"PG")
        else:
            write_cues(output, self.cues)
        if progress is not None:
            progress(1.0)


def work(tmp_path: Path, track: Track | None, output: str, kind: StepKind = StepKind.READ) -> StepWork:
    out = tmp_path / "kept" / output
    out.parent.mkdir(exist_ok=True)
    return StepWork(Step(kind), tmp_path / "video.mkv", None, None, ENGLISH, track, out)


def test_a_text_track_is_taken_out_as_the_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    extractor = Extractor()
    monkeypatch.setattr(reading, "extract_track", extractor)
    given = work(tmp_path, SRT, "result.srt")
    read_runner(Path("mkvextract"))(given, None)
    assert extractor.asked == [(2, ".srt")]
    assert read_cues(given.output) == extractor.cues
    # Nothing is left beside the result but the result.
    assert [p.name for p in given.output.parent.iterdir()] == ["result.srt"]


def test_a_styled_track_keeps_its_styles_and_is_converted_where_the_result_is_another_format(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extractor = Extractor([Cue(1, 2, "Hi", "Sign")])
    monkeypatch.setattr(reading, "extract_track", extractor)
    runner = read_runner(Path("mkvextract"))
    same = work(tmp_path, ASS, "result.ass")
    runner(same, None)
    assert [(c.text, c.style) for c in read_cues(same.output)] == [("Hi", "Sign")]
    assert extractor.asked[-1] == (3, ".ass")
    other = work(tmp_path, ASS, "reference.srt")
    runner(other, None)
    assert [(c.text, c.style) for c in read_cues(other.output)] == [("Hi", "")]


def test_a_track_that_cannot_be_taken_out_fails_and_leaves_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(reading, "extract_track", Extractor(error="no such track"))
    given = work(tmp_path, SRT, "result.srt")
    with pytest.raises(ExtractError, match="no such track"):
        read_runner(Path("mkvextract"))(given, None)
    assert list(given.output.parent.iterdir()) == []
    with pytest.raises(ValueError, match="needs the track"):
        read_runner(Path("mkvextract"))(work(tmp_path, None, "result.srt"), None)


def test_a_picture_track_is_read_by_ocr_and_always_gets_the_ocr_fixes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extractor = Extractor()
    monkeypatch.setattr(reading, "extract_track", extractor)
    streams: list[Path] = []

    def read(stream: Path, language: Language | None, tesseract: Path, **options: Any) -> list[Cue]:
        streams.append(stream)
        assert (stream.read_bytes(), tesseract, language) == (b"PG", Path("tesseract"), ENGLISH)
        options["progress"](0.5)
        return [Cue(1, 2, "Hte end"), Cue(3, 4, "Wait… what")]

    monkeypatch.setattr(reading, "read_pgs", read)
    mine = RuleSet(OCR_EXTRA, (RuleDef("mine", ("Hte",), replacement="The"),))
    book = RuleBook({**builtin_sets(), OCR_EXTRA: mine})
    seen: list[float] = []
    given = work(tmp_path, PGS, "reference.srt", StepKind.OCR)
    ocr_runner(Path("mkvextract"), Path("tesseract"), lambda: book)(replace(given, progress=seen.append), None)
    assert extractor.asked == [(4, ".sup")]
    assert [c.text for c in read_cues(given.output)] == ["The end", "Wait... what"]
    assert seen == [pytest.approx(0.1), pytest.approx(0.55)]
    # The stream is a scratch file: it is gone once the result is written.
    assert not streams[0].exists()


def test_the_lines_of_a_track_are_read_to_look_at_and_nothing_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    extractor = Extractor()
    monkeypatch.setattr(reading, "extract_track", extractor)
    assert track_cues(Path("mkvextract"), tmp_path / "v.mkv", SRT, ENGLISH, threading.Event()) == extractor.cues
