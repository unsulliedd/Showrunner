"""The sync step: any engine's outcome judged by the same two thresholds, a subtitle in sync kept as it is, and what the
step found kept beside its result."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.stages.subtitles import Step, StepKind, SyncEngine
from showrunner.stages.subtitles.sync import judge, read_report, sync_runner, thresholds
from showrunner.stages.subtitles.work import StepWork
from showrunner.tools.sync import IN_SYNC_BELOW, UNSURE_BELOW, Setting, SyncError, SyncOutcome, SyncRequest


class Engine:
    """Stands in for an engine: moves every line by `offset` and answers what it was told to."""

    name: ClassVar[str] = "ffsubsync"
    settings: ClassVar[tuple[Setting, ...]] = ()
    defaults: ClassVar[dict[str, str]] = {IN_SYNC_BELOW: "0.3", UNSURE_BELOW: "0.1"}

    def __init__(self, outcome: SyncOutcome, audio: bool = True) -> None:
        self.outcome, self.audio = outcome, audio
        self.requests: list[SyncRequest] = []

    def sync(self, request: SyncRequest) -> SyncOutcome:
        self.requests.append(request)
        cues = read_cues(request.subtitle)
        write_cues(request.output, [replace(c, start=c.start + self.outcome.offset) for c in cues])
        if request.progress is not None:
            request.progress(1.0)
        return self.outcome


def outcome(offset: float = 2.0, score: float = 0.5, **given: object) -> SyncOutcome:
    return SyncOutcome(offset, score=score, length=100.0, **given)  # type: ignore[arg-type]


def work(tmp_path: Path, reference: Path | None = None, settings: tuple[tuple[str, str], ...] = ()) -> StepWork:
    source = tmp_path / "in.srt"
    write_cues(source, [Cue(10.0, 12.0, "hello")])
    step = Step(StepKind.SYNC, engine=SyncEngine.FFSUBSYNC, settings=settings)
    return StepWork(step, tmp_path / "v.mkv", source, reference, Language("tur"), None, tmp_path / "result" / "out.srt")


def run(engine: Engine, given: StepWork, cancel: threading.Event | None = None) -> None:
    given.output.parent.mkdir(parents=True, exist_ok=True)
    sync_runner({"ffsubsync": engine})(given, cancel)


def test_a_subtitle_off_by_more_than_the_threshold_is_moved(tmp_path: Path) -> None:
    given = work(tmp_path)
    run(Engine(outcome(2.0)), given)
    assert [cue.start for cue in read_cues(given.output)] == [12.0]
    report = read_report(given.output)
    assert report is not None
    assert (report.offset, report.in_sync, report.needs_review) == (2.0, False, False)


def test_a_subtitle_already_in_sync_is_kept_byte_for_byte(tmp_path: Path) -> None:
    given = work(tmp_path)
    assert given.source is not None
    given.source.write_bytes("1\n00:00:10,000 --> 00:00:12,000\nmerhaba ş\n".encode("cp1254"))
    run(Engine(outcome(0.1)), given)
    assert given.output.read_bytes() == given.source.read_bytes()
    # The bytes are the original's, so a reader that is told the language reads them as it reads the original.
    assert read_cues(given.output, Language("tur")) == read_cues(given.source, Language("tur"))
    assert "ş" in read_cues(given.output, Language("tur"))[0].text
    report = read_report(given.output)
    assert report is not None
    assert report.in_sync
    assert report.shift == pytest.approx(0.1)


def test_a_stretch_counts_towards_being_in_sync(tmp_path: Path) -> None:
    # No offset, but a frame rate change moves the last line of a 100 s subtitle by 0.1 s, and of a 1000 s one by 1 s.
    adapter = Engine(outcome(0.0))
    assert judge(adapter, SyncOutcome(0.0, scale=1.001, length=100.0), {}).in_sync
    assert not judge(adapter, SyncOutcome(0.0, scale=1.001, length=1000.0), {}).in_sync


def test_a_low_score_or_the_engines_doubt_needs_review(tmp_path: Path) -> None:
    adapter = Engine(outcome())
    assert not judge(adapter, outcome(score=0.1), {}).needs_review
    assert judge(adapter, outcome(score=0.09), {}).needs_review
    assert judge(adapter, outcome(score=0.9, unsure=True), {}).needs_review


def test_the_places_thresholds_replace_the_engines_defaults(tmp_path: Path) -> None:
    adapter = Engine(outcome())
    settings = {IN_SYNC_BELOW: "3", UNSURE_BELOW: "0.7"}
    assert thresholds(adapter, settings) == (3.0, 0.7)
    report = judge(adapter, outcome(2.0, 0.6), settings)
    assert (report.in_sync, report.needs_review) == (True, True)
    # A value that is no number, or below zero, is the default.
    assert thresholds(adapter, {IN_SYNC_BELOW: "soon", UNSURE_BELOW: "-1"}) == (0.3, 0.1)


def test_the_step_gives_the_engine_what_it_needs(tmp_path: Path) -> None:
    reference = tmp_path / "reference.srt"
    given = work(tmp_path, reference, (("max_offset", "20"),))
    engine = Engine(outcome())
    seen: list[float] = []
    run(engine, replace(given, progress=seen.append))
    (request,) = engine.requests
    assert (request.subtitle, request.reference, request.output) == (given.source, reference, given.output)
    assert dict(request.settings) == {"max_offset": "20"}
    assert request.language == Language("tur")
    assert seen == [1.0]


def test_the_audio_needs_an_engine_that_can_listen(tmp_path: Path) -> None:
    with pytest.raises(SyncError, match="audio"):
        run(Engine(outcome(), audio=False), work(tmp_path))


def test_an_engine_that_is_not_there_is_refused(tmp_path: Path) -> None:
    given = work(tmp_path)
    given = replace(given, step=replace(given.step, engine=SyncEngine.ALASS))
    with pytest.raises(SyncError, match="alass"):
        run(Engine(outcome()), given)


def test_a_step_that_has_not_run_has_no_report(tmp_path: Path) -> None:
    assert read_report(tmp_path / "nothing.srt") is None
    (tmp_path / "bad.srt.sync.json").write_text("{", encoding="utf-8")
    assert read_report(tmp_path / "bad.srt") is None
