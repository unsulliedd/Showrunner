"""The translate step of a job: a wanted language the file lacks is translated from the reference, a translation where
windows fell back is not kept so the next run asks for them again, one where every window fell back fails the step,
and a wait for approval nothing can give leaves the translation out while the file's other work goes on."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from showrunner.app.jobs.results import ResultStore
from showrunner.app.jobs.stages import CleanupSets, PlanState, SubtitlesStage
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import SubtitleProperties, Track, TrackKind, VideoProperties
from showrunner.stages.subtitles import (
    AiModels,
    Approval,
    Output,
    RuleSetUse,
    StepKind,
    SubtitlePlan,
    SubtitlesOptions,
    Translate,
    Wanted,
)
from showrunner.stages.subtitles.translate import NOT_TRANSLATED, TranslateError, translate_runner
from showrunner.stages.subtitles.work import StepWork
from showrunner.tools.cleanit import RuleBook, RuleSet, builtin_sets

TRACKS = (
    Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080)),
    Track(1, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties()),
)
AI = AiModels("sample:9b", ("sample:9b",), window=2, context=1)
GERMAN = SubtitlesOptions(languages={"de": Wanted.WANTED})


def reading(work: StepWork, cancel: threading.Event | None) -> None:
    write_cues(work.output, [Cue(float(n), n + 0.5, f"line {n}") for n in range(4)])


def item(tmp_path: Path) -> MediaItem:
    video = tmp_path / "Show Name - S01E01.mkv"
    video.write_bytes(b"matroska")
    return MediaItem(Episode("Show Name", 1, 1), MediaFile(video, "matroska", tracks=TRACKS))


def stage(tmp_path: Path, backend: Any) -> SubtitlesStage:
    runners = {StepKind.READ: reading, StepKind.TRANSLATE: translate_runner(lambda: backend, RuleBook)}
    return SubtitlesStage(ResultStore(tmp_path / "results"), runners, CleanupSets(), ai=AI)


def test_a_translation_with_a_fallen_back_window_is_not_kept_and_the_next_run_retries_it(
    tmp_path: Path, translator: Any
) -> None:
    video, profile = item(tmp_path), Profile.defaults("Test").with_options("subtitles", GERMAN)
    first = stage(tmp_path, translator(down={"line 2"}))
    plan = first.plan(video, profile)
    assert first.apply(plan, None).ok
    work = plan.plan
    assert isinstance(work, SubtitlePlan)
    (german,) = work.finished
    result = first.results.final(work, german)
    assert [cue.text for cue in read_cues(result)] == ["tr line 0", "tr line 1", "line 2", "line 3"]
    report = first.results.translate_report(work, german)
    assert report is not None
    assert report.fell_back == (2,)
    # The next run reuses the answered window and asks only for the one that fell back.
    backend = translator()
    again = stage(tmp_path, backend)
    assert again.apply(again.plan(video, profile), None).ok
    assert len(backend.asked) == 1
    assert [cue.text for cue in read_cues(result)] == [f"tr line {n}" for n in range(4)]
    report = again.results.translate_report(work, german)
    assert report is not None
    assert not report.needs_review


def test_a_translation_where_every_window_fell_back_fails_the_step(tmp_path: Path, translator: Any) -> None:
    video, profile = item(tmp_path), Profile.defaults("Test").with_options("subtitles", GERMAN)
    failing = stage(tmp_path, translator(down={"line 0", "line 2"}))
    with pytest.raises(TranslateError, match=f"^{NOT_TRANSLATED}: 2$"):
        failing.apply(failing.plan(video, profile), None)


def test_a_translation_waiting_for_approval_is_left_out_until_a_view_can_approve(
    tmp_path: Path, translator: Any
) -> None:
    options = SubtitlesOptions(languages={"de": Wanted.WANTED}, approval=Approval.TRANSLATIONS)
    profile = Profile.defaults("Test").with_options("subtitles", options)
    plan = stage(tmp_path, translator()).plan(item(tmp_path), profile)
    work = plan.plan
    assert isinstance(work, SubtitlePlan)
    # Approval keeps its choice: the translation waits for a view that does not exist yet, so it is left out and
    # nothing of the file waits; its other changes plan as they would without it.
    assert [(f.language, f.missing) for f in work.left_out] == [(Language("deu"), (StepKind.APPROVAL,))]
    assert (work.finished, work.waits, plan.state) == ((), False, PlanState.UNCHANGED)


def test_a_second_always_run_beside_the_video_asks_nothing_and_leaves_the_ai_file(
    tmp_path: Path, translator: Any
) -> None:
    # A real scan pairs one Turkish file with the video and offers the other as an alternative, so the second run sees
    # the same item as the first, without the file the first wrote.
    paired = tmp_path / "Show Name - S01E01.tr.srt"
    write_cues(paired, [Cue(1.0, 1.5, "eski")])
    video = replace(item(tmp_path), subtitles=(SubtitleFile(paired, Language("tur")),))
    options = SubtitlesOptions(languages={"tr": Wanted.WANTED}, translate=Translate.ALWAYS, output=Output.NEW_FILE)
    profile = Profile.defaults("Test").with_options("subtitles", options)
    first = stage(tmp_path, translator())
    assert first.apply(first.plan(video, profile), None).ok
    written = tmp_path / "Show Name - S01E01_ai.tr.srt"
    assert [cue.text for cue in read_cues(written)] == [f"tr line {n}" for n in range(4)]
    assert [cue.text for cue in read_cues(paired)] == ["eski"]
    stamp = written.stat().st_mtime_ns
    backend = translator()
    again = stage(tmp_path, backend)
    assert again.apply(again.plan(video, profile), None).ok
    assert backend.asked == []
    assert written.stat().st_mtime_ns == stamp
    assert [cue.text for cue in read_cues(paired)] == ["eski"]


def test_a_kept_translation_is_made_again_when_a_rule_of_its_sets_changes(tmp_path: Path) -> None:
    """The reference's cleanup and the translation's are part of the result's name, so new rules make a new one."""
    video = item(tmp_path)
    options = replace(GERMAN, cleanup={"no-sdh": RuleSetUse.USED})
    profile = Profile.defaults("Test").with_options("subtitles", options)
    sets = builtin_sets()

    def paths(no_sdh: RuleSet) -> tuple[Path, Path]:
        runners = {StepKind.READ: reading, StepKind.TRANSLATE: reading, StepKind.CLEAN: reading}
        found = SubtitlesStage(ResultStore(tmp_path), runners, CleanupSets({"no-sdh": no_sdh}), ai=AI)
        work = found.plan(video, profile).plan
        assert isinstance(work, SubtitlePlan)
        (german,) = work.finished
        assert [step.kind for step in german.steps] == [StepKind.TRANSLATE, StepKind.CLEAN]
        return found.results.output(work, german, 0), found.results.final(work, german)

    fewer = replace(sets["no-sdh"], rules=sets["no-sdh"].rules[:-1])
    assert not set(paths(sets["no-sdh"])) & set(paths(fewer))
