"""How the views word a re-split: by timing, or with the model and the windows that went by timing, and the window it
asks for while it runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.app.jobs.results import ResultStore
from showrunner.core.language import Language
from showrunner.core.media import SubtitleFile
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.subtitles import (
    FinishedSubtitle,
    Lines,
    ReferenceTrack,
    Source,
    Step,
    StepKind,
    SubtitlePlan,
    SyncEngine,
)
from showrunner.stages.subtitles.resplit_ai import ResplitReport, write_report
from showrunner.ui.quick import review
from showrunner.ui.quick.jobs import resplit_text, window_text

ENGLISH = Track(2, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties())
SYNC = Step(StepKind.SYNC, engine=SyncEngine.ALASS)
WITH_AI = Step(StepKind.RESPLIT, settings=(("window", "40"),), model="sample:9b", way=Lines.WITH_AI)


def plan(resplit: Step) -> tuple[SubtitlePlan, FinishedSubtitle]:
    paired = SubtitleFile(Path("Show.tr.srt"), Language("tur"))
    finished = FinishedSubtitle(Source.PAIRED, Language("tur"), (SYNC, resplit), "srt", paired)
    return SubtitlePlan(Path("Show.mkv"), (finished,), ReferenceTrack(ENGLISH)), finished


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ResultStore:
    monkeypatch.setattr(review, "results_dir", lambda: tmp_path)
    return ResultStore(tmp_path)


def report(store: ResultStore, found: ResplitReport) -> SubtitlePlan:
    work, finished = plan(WITH_AI)
    output = store.output(work, finished, 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_report(output, found)
    return work


def test_by_timing_says_so_with_no_windows(store: ResultStore) -> None:
    work, _ = plan(Step(StepKind.RESPLIT, way=Lines.BY_TIMING))
    assert resplit_text(work) == ["Turkish subtitle: re-split by timing"]
    assert window_text(work, "resplit") == ""


def test_with_ai_names_the_model_and_the_windows_that_went_by_timing(store: ResultStore) -> None:
    work = report(store, ResplitReport("sample:9b", 14, 14, by_timing=(3, 9)))
    assert resplit_text(work) == ["Turkish subtitle: re-split with sample:9b · windows 3, 9 of 14 went by timing"]
    work = report(store, ResplitReport("sample:9b", 2, 2, by_timing=(1, 2)))
    assert resplit_text(work) == ["Turkish subtitle: re-split with sample:9b · all 2 windows went by timing"]
    work = report(store, ResplitReport("sample:9b", 14, 14))
    assert resplit_text(work) == ["Turkish subtitle: re-split with sample:9b"]


def test_a_running_resplit_with_ai_says_which_window_it_asks_for(store: ResultStore) -> None:
    work = report(store, ResplitReport("sample:9b", 14, 4))
    assert window_text(work, "resplit") == "window 5 of 14"
    # The translation's window is another report.
    assert window_text(work, "translate") == ""
