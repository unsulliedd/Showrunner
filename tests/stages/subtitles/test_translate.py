"""The translate step: the reference cleaned for its language, translated window by window with its own timing, and a
report of what fell back kept beside the result."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.stages.subtitles import Step, StepKind
from showrunner.stages.subtitles.translate import (
    NOT_TRANSLATED,
    TranslateError,
    TranslateReport,
    read_report,
    translate_runner,
    window_settings,
)
from showrunner.stages.subtitles.work import StepWork
from showrunner.tools.cleanit import RuleBook, RuleDef, RuleSet

ENGLISH, TURKISH = Language("eng"), Language("tur")


def book() -> RuleBook:
    return RuleBook({"Ads": RuleSet("Ads", (RuleDef(name="ad", patterns=("Visit .*",)),))})


@pytest.fixture
def reference(tmp_path: Path) -> Path:
    path = tmp_path / "reference.srt"
    cues = [Cue(float(n), n + 0.5, f"line {n}") for n in range(9)]
    write_cues(path, [*cues[:4], Cue(4.2, 4.4, "Visit example.com"), *cues[4:]])
    return path


def work(reference: Path, tmp_path: Path, sets: tuple[str, ...] = ("Ads",), size: int = 4) -> StepWork:
    step = Step(StepKind.TRANSLATE, sets, settings=(("context", "1"), ("window", str(size))), model="sample:9b")
    return StepWork(step, tmp_path / "v.mkv", None, reference, TURKISH, None, tmp_path / "out" / "tr.srt", ENGLISH)


def test_every_cue_is_translated_with_the_reference_s_timing_after_its_cleanup(
    reference: Path, tmp_path: Path, translator: Any
) -> None:
    backend = translator()
    given = work(reference, tmp_path)
    given.output.parent.mkdir()
    translate_runner(lambda: backend, book)(given, None)
    cues = read_cues(given.output, TURKISH)
    # The ad was cleaned out of the reference before it was translated.
    assert [cue.text for cue in cues] == [f"tr line {n}" for n in range(9)]
    assert [cue.start for cue in cues] == [float(n) for n in range(9)]
    assert read_report(given.output) == TranslateReport("sample:9b", 3, 3)
    assert "from English into Turkish" in backend.asked[0].system
    assert {request.temperature for request in backend.asked} == {0.0}


def test_a_window_that_falls_back_keeps_the_reference_and_is_reported(
    reference: Path, tmp_path: Path, translator: Any
) -> None:
    backend = translator(bad={"line 4"}, down={"line 8"})
    given = work(reference, tmp_path)
    given.output.parent.mkdir()
    translate_runner(lambda: backend, book)(given, None)
    texts = [cue.text for cue in read_cues(given.output, TURKISH)]
    assert texts == [*(f"tr line {n}" for n in range(4)), *(f"line {n}" for n in range(4, 9))]
    report = read_report(given.output)
    assert report == TranslateReport("sample:9b", 3, 3, fell_back=(2, 3), retried=1)
    assert report.needs_review
    # The second run asks again for the fallen-back windows only.
    rerun = translator()
    translate_runner(lambda: rerun, book)(given, None)
    assert len(rerun.asked) == 2
    assert read_report(given.output) == TranslateReport("sample:9b", 3, 3, reused=1)


def test_a_translation_where_every_window_fell_back_fails(reference: Path, tmp_path: Path, translator: Any) -> None:
    given = work(reference, tmp_path, sets=(), size=40)
    given.output.parent.mkdir()
    with pytest.raises(TranslateError, match=f"^{NOT_TRANSLATED}: 1$"):
        translate_runner(lambda: translator(down={"line 0"}), book)(given, None)
    assert not given.output.exists()
    assert read_report(given.output) == TranslateReport("sample:9b", 1, 1, fell_back=(1,))


def test_the_report_says_how_far_the_step_is_after_each_window(
    reference: Path, tmp_path: Path, translator: Any
) -> None:
    given = work(reference, tmp_path)
    given.output.parent.mkdir()
    seen: list[TranslateReport | None] = []
    tracked = replace(given, progress=lambda _: seen.append(read_report(given.output)))
    translate_runner(lambda: translator(), book)(tracked, None)
    assert [(r.done, r.windows) for r in seen if r is not None] == [(1, 3), (2, 3), (3, 3)]


def test_window_settings_fall_back_to_the_defaults_and_context_stays_below_the_window() -> None:
    assert window_settings({}) == (40, 5)
    assert window_settings({"window": "20", "context": "3"}) == (20, 3)
    assert window_settings({"window": "0", "context": "x"}) == (40, 5)
    assert window_settings({"window": "4", "context": "9"}) == (4, 3)
