"""How the views word a translation: the model, the window it asks for while it runs, the windows that fell back and
the needs-review mark, and why a translation stopped."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.jobs.results import ResultStore
from showrunner.app.jobs.stages import PlanState, StagePlan
from showrunner.core.language import Language
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.subtitles import FinishedSubtitle, ReferenceTrack, Source, Step, StepKind, SubtitlePlan
from showrunner.stages.subtitles.translate import TranslateReport, write_report
from showrunner.ui.quick import review
from showrunner.ui.quick.jobs import reason_text, translate_text, window_text
from showrunner.ui.quick.review import translation_found

ENGLISH = Track(2, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties())
TURKISH = FinishedSubtitle(
    Source.TRANSLATION, Language("tur"), (Step(StepKind.TRANSLATE, model="sample:9b"), Step(StepKind.CLEAN)), "srt"
)
PLAN = SubtitlePlan(Path("Show.mkv"), (TURKISH,), ReferenceTrack(ENGLISH))


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ResultStore:
    monkeypatch.setattr(review, "results_dir", lambda: tmp_path)
    return ResultStore(tmp_path)


def report(store: ResultStore, found: TranslateReport) -> None:
    output = store.output(PLAN, TURKISH, 0)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_report(output, found)


def test_a_running_translation_says_which_window_it_asks_for(store: ResultStore) -> None:
    assert window_text(PLAN) == ""
    report(store, TranslateReport("sample:9b", 14, 2))
    assert window_text(PLAN) == "window 3 of 14"
    # Nothing is said of a translation still running.
    assert translate_text(PLAN) == []
    report(store, TranslateReport("sample:9b", 14, 14))
    assert window_text(PLAN) == ""


def test_a_finished_translation_names_its_model_and_the_windows_that_fell_back(store: ResultStore) -> None:
    assert translation_found(TranslateReport("sample:9b", 14, 14)) == "translated with sample:9b"
    assert translation_found(TranslateReport("sample:9b", 14, 14, fell_back=(3,))) == (
        "translated with sample:9b · needs review: window 3 of 14 kept the reference's text"
    )
    report(store, TranslateReport("sample:9b", 14, 14, fell_back=(3, 9)))
    assert translate_text(PLAN) == [
        "Turkish subtitle: translated with sample:9b · needs review: windows 3, 9 of 14 kept the reference's text"
    ]


def test_a_stopped_translation_says_why() -> None:
    assert reason_text("not-translated: 14").startswith("Every window of the translation (14) fell back")
    assert reason_text("unreachable: timed out").startswith("Ollama stopped answering")
    assert "model 'gone:1b' not found" in reason_text("model-missing: model 'gone:1b' not found")


class Preview:
    """Stands in for a file's preview, with its subtitle plan alone."""

    def plan_for(self, stage: str) -> StagePlan | None:
        return StagePlan("subtitles", PlanState.CHANGES, PLAN) if stage == "subtitles" else None


def test_review_names_the_model_and_what_the_last_run_found(store: ResultStore) -> None:
    def translation() -> str:
        rows = review._subtitle_lines(Preview(), False)  # type: ignore[arg-type]
        return next(str(row["text"]) for row in rows if row["label"] == "Translation")

    assert translation() == "Turkish is translated from the reference with sample:9b"
    report(store, TranslateReport("sample:9b", 14, 14, fell_back=(3,)))
    assert translation() == (
        "Turkish is translated from the reference with sample:9b · needs review: window 3 of 14 kept the"
        " reference's text"
    )


class Planned:
    """Stands in for a file's preview, with the subtitle plan given."""

    def __init__(self, plan: SubtitlePlan) -> None:
        self.plan = plan

    def plan_for(self, stage: str) -> StagePlan | None:
        return StagePlan("subtitles", PlanState.CHANGES, self.plan) if stage == "subtitles" else None


def test_a_translation_made_always_says_it_is_new_next_to_the_existing_subtitle(store: ResultStore) -> None:
    always = replace(TURKISH, existing=True, name="AI translation")
    beside = replace(always, target=Path("Show_ai.tr.srt"))
    plan = SubtitlePlan(Path("Show.mkv"), (always, beside), ReferenceTrack(ENGLISH))
    texts = [row["text"] for row in review._subtitle_lines(Planned(plan), False)][:2]  # type: ignore[arg-type]
    assert texts == [
        "Turkish: goes into the new file as an extra track named AI translation, next to the subtitle already there.",
        "Turkish: written beside the video as Show_ai.tr.srt, next to the subtitle already there.",
    ]
    output = store.output(plan, always, 0)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_report(output, TranslateReport("sample:9b", 14, 14))
    assert translate_text(SubtitlePlan(Path("Show.mkv"), (always,), ReferenceTrack(ENGLISH)))[0] == (
        "Turkish subtitle, new next to the existing one: translated with sample:9b"
    )


def test_a_translation_an_earlier_run_put_into_the_video_names_its_track() -> None:
    earlier = replace(TURKISH, existing=True, name="AI translation")
    plan = SubtitlePlan(Path("Show.mkv"), written_earlier=(earlier,))
    (row,) = review._subtitle_lines(Planned(plan), False)  # type: ignore[arg-type]
    assert row["text"] == "Written earlier: the track AI translation"
