"""Translating every wanted language whatever subtitles the file has: the existing ones stay as they are, the
translation is named so it never takes their place, and a rerun finds what an earlier run made."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.options.serialization import from_sparse
from showrunner.stages.subtitles import (
    Output,
    RuleSetUse,
    Source,
    StepKind,
    SubtitlesOptions,
    Translate,
    Wanted,
    plan_subtitles,
)
from showrunner.stages.subtitles.beside import is_result
from showrunner.stages.subtitles.options import ai_name_problem, ai_text_problem, bad_new_file_text
from showrunner.stages.tracks import TracksOptions
from showrunner.tools.cleanit import RuleDef, RuleSet

TURKISH = SubtitleFile(Path("Show Name - S01E01.tr.srt"), Language("tur"))
AI_FILE = SubtitleFile(Path("Show Name - S01E01_ai.tr.srt"), Language("tur"))
SETS = {"Lyrics": RuleSet("Lyrics", (RuleDef(name="rule", patterns=("x",)),))}
ALWAYS = SubtitlesOptions(languages={"tr": Wanted.WANTED}, translate=Translate.ALWAYS)


def episode(b: SimpleNamespace, paired: tuple[SubtitleFile, ...] = (TURKISH,)) -> MediaItem:
    return b.item(b.video(0), b.audio(1), b.subtitle(2), subtitles=paired)


def cleaning(output: Output) -> SubtitlesOptions:
    return SubtitlesOptions(
        languages={"tr": Wanted.WANTED},
        translate=Translate.ALWAYS,
        output=output,
        cleanup={"Lyrics": RuleSetUse.USED},
    )


def test_when_missing_translates_nothing_the_file_has(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"tr": Wanted.WANTED})
    assert plan_subtitles(episode(b), options, TracksOptions()).finished == ()


def test_always_translates_next_to_the_existing_subtitle_into_the_video(b: SimpleNamespace) -> None:
    plan = plan_subtitles(episode(b), ALWAYS, TracksOptions())
    (finished,) = plan.finished
    assert (finished.source, finished.language, finished.target) == (Source.TRANSLATION, Language("tur"), None)
    assert [s.kind for s in finished.steps] == [StepKind.TRANSLATE]
    assert (finished.existing, finished.name) == (True, "AI translation")
    assert plan.reference is not None
    assert plan.reference.track == b.subtitle(2)


def test_always_never_translates_the_reference_language_from_itself(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"en": Wanted.WANTED, "tr": Wanted.WANTED}, translate=Translate.ALWAYS)
    plan = plan_subtitles(episode(b), options, TracksOptions())
    assert [f.language for f in plan.finished] == [Language("tur")]


def test_always_without_an_existing_subtitle_is_a_named_translation_too(b: SimpleNamespace) -> None:
    (finished,) = plan_subtitles(episode(b, paired=()), ALWAYS, TracksOptions()).finished
    assert (finished.existing, finished.name) == (False, "AI translation")


@pytest.mark.parametrize("output", [Output.NEW_FILE, Output.REPLACE])
def test_beside_the_video_the_translation_is_named_with_the_ai_text(b: SimpleNamespace, output: Output) -> None:
    plan = plan_subtitles(episode(b), cleaning(output), TracksOptions(), rule_sets=SETS)
    translation = next(f for f in plan.finished if f.source is Source.TRANSLATION)
    assert translation.target == Path("Show Name - S01E01_ai.tr.srt")
    # The existing file gets the work the place asks for it, as it would without the translation.
    assert [f.paired for f in plan.finished if f.source is Source.PAIRED] == [TURKISH]
    assert plan.cannot == ()


def test_when_missing_beside_keeps_the_name_by_language(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"de": Wanted.WANTED}, output=Output.NEW_FILE)
    (finished,) = plan_subtitles(episode(b), options, TracksOptions()).finished
    assert (finished.target, finished.existing, finished.name) == (Path("Show Name - S01E01.de.srt"), False, "")


@pytest.mark.parametrize("output", [Output.NEW_FILE, Output.REPLACE])
def test_a_rerun_beside_finds_the_ai_file_and_never_works_on_it(b: SimpleNamespace, output: Output) -> None:
    plan = plan_subtitles(episode(b, paired=(TURKISH, AI_FILE)), cleaning(output), TracksOptions(), rule_sets=SETS)
    # Only the existing file is cleaned; the AI file is no source of work.
    assert [f.paired for f in plan.finished] == [TURKISH]
    (earlier,) = plan.written_earlier
    assert (earlier.source, earlier.target) == (Source.TRANSLATION, AI_FILE.path)


def test_a_rerun_into_the_video_finds_the_named_track_and_never_translates_from_it(b: SimpleNamespace) -> None:
    made = b.subtitle(3, "ai translation", language="tur")
    # With no English track, Automatic would take the earlier translation, a text track, as the reference.
    item = b.item(b.video(0), b.audio(1), made, subtitles=())
    plan = plan_subtitles(item, ALWAYS, TracksOptions())
    assert plan.finished == ()
    (earlier,) = plan.written_earlier
    assert (earlier.target, earlier.name) == (None, "AI translation")
    german = plan_subtitles(item, SubtitlesOptions(languages={"de": Wanted.WANTED}), TracksOptions())
    assert german.finished == ()
    assert [f.source for f in german.cannot] == [Source.TRANSLATION]


def test_the_ai_text_names_results_and_is_checked_like_the_new_file_text() -> None:
    assert is_result(AI_FILE.path.name, "_ai")
    assert not is_result(TURKISH.path.name, "_ai")
    for bad in ("", "a/b", "x:y"):
        assert bad_new_file_text(bad)
        assert ai_text_problem(SubtitlesOptions(translate=Translate.ALWAYS, output=Output.NEW_FILE, ai_file_text=bad))
        # Read only beside the video, and only when translating always.
        assert not ai_text_problem(SubtitlesOptions(translate=Translate.ALWAYS, ai_file_text=bad))
        assert not ai_text_problem(SubtitlesOptions(output=Output.NEW_FILE, ai_file_text=bad))
    assert not ai_text_problem(SubtitlesOptions(translate=Translate.ALWAYS, output=Output.NEW_FILE))


def test_an_empty_track_name_is_a_problem_only_where_it_names_a_track() -> None:
    assert ai_name_problem(SubtitlesOptions(translate=Translate.ALWAYS, ai_track_name=" "))
    assert not ai_name_problem(SubtitlesOptions(translate=Translate.ALWAYS, output=Output.NEW_FILE, ai_track_name=""))
    assert not ai_name_problem(SubtitlesOptions(ai_track_name=""))
    assert not ai_name_problem(SubtitlesOptions(translate=Translate.ALWAYS))


def test_options_saved_before_the_translate_row_load_as_when_missing() -> None:
    loaded = from_sparse(SubtitlesOptions, {"languages": {"tr": "wanted"}}, "subtitles", [])
    assert (loaded.translate, loaded.ai_file_text, loaded.ai_track_name) == (
        Translate.WHEN_MISSING,
        "_ai",
        "AI translation",
    )
