from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.subtitles import (
    Approval,
    Cannot,
    Lines,
    Output,
    Reference,
    ReferenceKind,
    RuleSetUse,
    Source,
    Step,
    StepKind,
    SubtitlePlan,
    SubtitlesOptions,
    SyncEngine,
    Wanted,
)
from showrunner.stages.subtitles import plan_subtitles as _plan
from showrunner.stages.tracks import KindTest, PairedFile, TrackMatch, TrackRule, TracksOptions, Verdict
from showrunner.tools.cleanit import RuleDef, RuleSet

TURKISH = SubtitleFile(Path("Show Name - S01E01.tr.srt"), Language("tur"))
CLEAN = {"Hearing impaired": RuleSetUse.USED, "Lyrics": RuleSetUse.USED}


def _set(name: str, *languages: str) -> RuleSet:
    return RuleSet(name, (RuleDef(name=f"{name} rule", patterns=("x",), languages=languages),))


SETS = {name: _set(name) for name in ("Hearing impaired", "Lyrics", "Ads")}


def plan_subtitles(*args: Any, **kwargs: Any) -> SubtitlePlan:
    """The plan with the three sets above existing, which work on every language."""
    return _plan(*args, **{"rule_sets": SETS} | kwargs)


def cleaning(*names: str, sets: dict[str, RuleSet] = SETS) -> Step:
    """The step that cleans with the sets, made from the sets as the plan reads them."""
    return Step(StepKind.CLEAN, names, "+".join(f"{n}:{sets[n].fingerprint}" for n in names))


ADD_TURKISH = TracksOptions(add_paired=[PairedFile.of(TURKISH)])


def pgs(track_id: int, language: str = "eng") -> Track:
    return Track(
        track_id,
        TrackKind.SUBTITLE,
        "S_HDMV/PGS",
        Language.parse(language),
        subtitle=SubtitleProperties(text_based=False),
    )


def episode(b: SimpleNamespace, *subtitles: Track, paired: tuple[SubtitleFile, ...] = (TURKISH,)) -> MediaItem:
    return b.item(b.video(0), b.audio(1), *subtitles, subtitles=paired)


def test_options_that_ask_for_nothing_plan_nothing(b: SimpleNamespace) -> None:
    item = episode(b, b.subtitle(2))
    assert plan_subtitles(item, SubtitlesOptions(), ADD_TURKISH).finished == ()
    # A paired file the track plan adds is muxed as it is until the place asks for work on it.
    assert plan_subtitles(item, SubtitlesOptions(approval=Approval.EVERY), ADD_TURKISH).finished == ()


def test_a_paired_file_the_tracks_add_is_cleaned_synced_and_resplit(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(
        cleanup={"Lyrics": RuleSetUse.USED, "Hearing impaired": RuleSetUse.USED, "Ads": RuleSetUse.PAUSED},
        sync=SyncEngine.ALASS,
        sync_settings={"alass.split_penalty": "7", "ffsubsync.max_offset": "60", "alass.splits": ""},
        lines=Lines.RESPLIT,
        model="Sample 9B Instruct",
    )
    plan = plan_subtitles(episode(b, b.subtitle(2)), options, ADD_TURKISH)
    (finished,) = plan.finished
    assert (finished.source, finished.paired, finished.format, finished.waits) == (Source.PAIRED, TURKISH, "srt", False)
    assert finished.steps == (
        cleaning("Hearing impaired", "Lyrics"),  # sorted, paused sets left out
        Step(StepKind.SYNC, engine=SyncEngine.ALASS, settings=(("split_penalty", "7"),)),
        Step(StepKind.RESPLIT, model="Sample 9B Instruct"),
    )
    # Sync and re-split work against the English text track.
    assert plan.reference is not None
    assert plan.reference.track == b.subtitle(2)


def test_a_paired_file_the_tracks_do_not_add_gets_no_work(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(cleanup=CLEAN, sync=SyncEngine.FFSUBSYNC)
    plan = plan_subtitles(episode(b, b.subtitle(2)), options, TracksOptions())
    assert plan.finished == ()
    assert plan.not_added == (TURKISH,)  # named, so the views can say why nothing happens
    # Nor does one the rules drop after adding it.
    drop = TrackRule(match=TrackMatch(kind=KindTest.SUBTITLE, languages=["tr"]), verdict=Verdict.DROP)
    dropped = replace(ADD_TURKISH, rules=[drop])
    assert plan_subtitles(episode(b, b.subtitle(2)), options, dropped).finished == ()
    assert plan_subtitles(episode(b, b.subtitle(2)), options, ADD_TURKISH).not_added == ()


def test_resplit_runs_only_after_a_sync(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(cleanup=CLEAN, lines=Lines.RESPLIT)
    (finished,) = plan_subtitles(episode(b, b.subtitle(2)), options, ADD_TURKISH).finished
    assert [s.kind for s in finished.steps] == [StepKind.CLEAN]


def test_a_missing_wanted_language_is_translated_and_waits_when_asked(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(
        languages={"de": Wanted.WANTED, "tr": Wanted.WANTED, "fr": Wanted.NOT_HERE},
        cleanup=CLEAN,
        approval=Approval.TRANSLATIONS,
    )
    plan = plan_subtitles(episode(b, pgs(2)), options, TracksOptions())
    # Turkish lies beside the video, so only German is missing; French is not wanted here.
    (german,) = plan.finished
    assert (german.source, german.language, german.waits, german.format) == (
        Source.TRANSLATION,
        Language("deu"),
        True,
        "srt",
    )
    assert german.steps == (
        replace(cleaning("Hearing impaired", "Lyrics"), kind=StepKind.TRANSLATE),
        cleaning("Hearing impaired", "Lyrics"),
    )
    # The only subtitle is a picture one, read by OCR.
    assert plan.reference is not None
    assert plan.reference.step == Step(StepKind.OCR)


def test_a_translation_without_a_subtitle_to_translate_from_cannot_be_made(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"de": Wanted.WANTED})
    plan = plan_subtitles(episode(b), options, TracksOptions())
    assert plan.finished == ()
    assert [(c.language, c.cannot) for c in plan.cannot] == [(Language("deu"), (Cannot.NO_REFERENCE,))]
    assert plan.reference is None
    audio = replace(options, reference=Reference(ReferenceKind.AUDIO))
    assert plan_subtitles(episode(b, b.subtitle(2)), audio, TracksOptions()).cannot[0].cannot == (Cannot.NO_REFERENCE,)


def test_an_embedded_text_track_in_a_wanted_language_is_cleaned(b: SimpleNamespace) -> None:
    ass = replace(b.subtitle(3, language="tur"), codec="S_TEXT/ASS")
    options = SubtitlesOptions(languages={"tr": Wanted.WANTED}, cleanup=CLEAN, approval=Approval.EVERY)
    plan = plan_subtitles(episode(b, b.subtitle(2), ass, paired=()), options, TracksOptions())
    (turkish,) = plan.finished
    assert (turkish.source, turkish.track, turkish.format, turkish.waits) == (Source.EMBEDDED, ass, "ass", True)
    assert [s.kind for s in turkish.steps] == [StepKind.READ, StepKind.CLEAN]
    # Cleaning reads the track itself; nothing works against a reference.
    assert plan.reference is None
    # Without a rule set nothing is asked of it.
    assert plan_subtitles(episode(b, ass, paired=()), replace(options, cleanup={}), TracksOptions()).finished == ()


def test_automatic_prefers_the_reference_language_then_text_over_pictures(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"de": Wanted.WANTED})
    spanish, english_pgs = b.subtitle(2, language="spa"), pgs(3, "eng")
    item = episode(b, spanish, english_pgs, paired=())
    assert plan_subtitles(item, options, TracksOptions()).reference.track == english_pgs
    assert plan_subtitles(item, options, TracksOptions(), prefer="fr").reference.track == spanish


def test_a_chosen_reference_group_falls_back_to_automatic_where_a_file_lacks_it(b: SimpleNamespace) -> None:
    chosen = Reference(ReferenceKind.TRACK, TrackMatch(kind=KindTest.SUBTITLE, languages=["fr"]))
    options = SubtitlesOptions(languages={"de": Wanted.WANTED}, reference=chosen)
    french = b.subtitle(4, language="fre")
    with_french = plan_subtitles(episode(b, b.subtitle(2), french, paired=()), options, TracksOptions()).reference
    assert (with_french.track, with_french.fallback) == (french, False)
    without = plan_subtitles(episode(b, b.subtitle(2), paired=()), options, TracksOptions()).reference
    assert (without.track, without.fallback) == (b.subtitle(2), True)


def test_a_subtitle_needing_work_that_cannot_run_is_left_out(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(cleanup=CLEAN, sync=SyncEngine.ALASS, languages={"de": Wanted.WANTED})
    item = episode(b, b.subtitle(2))
    can_clean = (StepKind.READ, StepKind.CLEAN)
    plan = plan_subtitles(item, options, ADD_TURKISH, available=can_clean)
    assert plan.finished == ()
    assert [(f.source, f.missing) for f in plan.left_out] == [
        (Source.PAIRED, (StepKind.SYNC,)),
        (Source.TRANSLATION, (StepKind.TRANSLATE,)),
    ]
    # Nothing ready works against the reference, so none is read.
    assert plan.reference is None
    # The reading of the reference is work too: without it the sync is left out even with its engine.
    no_read = plan_subtitles(item, options, ADD_TURKISH, available=(StepKind.CLEAN, StepKind.SYNC))
    assert no_read.left_out[0].missing == (StepKind.READ,)
    # Cleaning alone needs no reference, so it is planned.
    cleaned = plan_subtitles(
        item, replace(options, sync=SyncEngine.AS_IT_IS, languages={}), ADD_TURKISH, available=can_clean
    )
    assert [f.source for f in cleaned.finished] == [Source.PAIRED]


def test_a_wait_for_approval_is_work_that_must_be_available(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(cleanup=CLEAN, approval=Approval.EVERY)
    without = (StepKind.CLEAN,)
    plan = plan_subtitles(episode(b, b.subtitle(2)), options, ADD_TURKISH, available=without)
    assert [f.missing for f in plan.left_out] == [(StepKind.APPROVAL,)]
    plan = plan_subtitles(episode(b, b.subtitle(2)), options, ADD_TURKISH, available=(*without, StepKind.APPROVAL))
    assert plan.waits


def test_a_set_cleans_only_the_languages_its_rules_are_for(b: SimpleNamespace) -> None:
    sets = SETS | {"Turkish only": _set("Turkish only", "tr"), "English only": _set("English only", "en-US")}
    options = SubtitlesOptions(cleanup=dict.fromkeys(("Lyrics", "Turkish only", "English only"), RuleSetUse.USED))
    (finished,) = _plan(episode(b, b.subtitle(2)), options, ADD_TURKISH, rule_sets=sets).finished
    # Turkish is cleaned by the set for every language and by the one for Turkish; a region does not matter.
    assert finished.steps == (cleaning("Lyrics", "Turkish only", sets=sets),)
    english = SubtitleFile(Path("Show Name - S01E01.en.srt"), Language("eng"))
    both = TracksOptions(add_paired=[PairedFile.of(english)])
    (finished,) = _plan(episode(b, paired=(english,)), options, both, rule_sets=sets).finished
    assert finished.steps == (cleaning("English only", "Lyrics", sets=sets),)


def test_a_set_that_does_not_exist_cleans_nothing(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(cleanup={"Deleted": RuleSetUse.USED})
    assert plan_subtitles(episode(b, b.subtitle(2)), options, ADD_TURKISH).finished == ()
    # A subtitle of no known language gets the sets whose rules have no language only.
    nameless = SubtitleFile(Path("Show Name - S01E01.srt"), None)
    sets = SETS | {"Turkish only": _set("Turkish only", "tr")}
    options = SubtitlesOptions(cleanup={"Lyrics": RuleSetUse.USED, "Turkish only": RuleSetUse.USED})
    plan = _plan(
        episode(b, paired=(nameless,)), options, TracksOptions(add_paired=[PairedFile.of(nameless)]), rule_sets=sets
    )
    assert [f.steps for f in plan.finished] == [(cleaning("Lyrics", sets=sets),)]


def test_a_rule_that_changes_changes_the_step(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(cleanup=CLEAN)
    edited = SETS | {"Lyrics": RuleSet("Lyrics", (RuleDef(name="Lyrics rule", patterns=("y",)),))}
    before = _plan(episode(b, b.subtitle(2)), options, ADD_TURKISH, rule_sets=SETS).finished[0].steps
    after = _plan(episode(b, b.subtitle(2)), options, ADD_TURKISH, rule_sets=edited).finished[0].steps
    assert before != after
    paused = SETS | {"Lyrics": RuleSet("Lyrics", (RuleDef(name="Lyrics rule", patterns=("x",), paused=True),))}
    # A set whose rules are all paused has nothing to clean with.
    assert (
        _plan(
            episode(b, b.subtitle(2)),
            SubtitlesOptions(cleanup={"Lyrics": RuleSetUse.USED}),
            ADD_TURKISH,
            rule_sets=paused,
        ).finished
        == ()
    )


# Beside the video

CLEAN_HI = SubtitlesOptions(cleanup={"Hearing impaired": RuleSetUse.USED})


def beside(output: Output, base: SubtitlesOptions = CLEAN_HI) -> SubtitlesOptions:
    return replace(base, output=output)


def test_into_the_video_has_no_target(b: SimpleNamespace) -> None:
    plan = plan_subtitles(episode(b), CLEAN_HI, ADD_TURKISH)
    (finished,) = plan.finished
    assert finished.target is None
    assert plan.into_video == plan.finished
    assert plan.written == ()


def test_beside_reaches_a_paired_file_tracks_does_not_add(b: SimpleNamespace) -> None:
    item = episode(b)
    assert plan_subtitles(item, CLEAN_HI, TracksOptions()).finished == ()
    plan = plan_subtitles(item, beside(Output.REPLACE), TracksOptions())
    (finished,) = plan.finished
    assert finished.source is Source.PAIRED
    assert finished.target == TURKISH.path
    assert finished.replaces
    assert plan.into_video == ()
    assert plan.not_added == ()


def test_a_new_file_is_named_with_the_text(b: SimpleNamespace) -> None:
    options = beside(Output.NEW_FILE)
    (finished,) = plan_subtitles(episode(b), options, ADD_TURKISH).finished
    assert finished.target == Path("Show Name - S01E01_cleaned.tr.srt")
    assert not finished.replaces


def test_a_rerun_after_a_new_file_run_plans_nothing_and_flags_nothing(b: SimpleNamespace) -> None:
    done = SubtitleFile(Path("Show Name - S01E01_cleaned.tr.srt"), Language("tur"))
    plan = plan_subtitles(episode(b, paired=(TURKISH, done)), beside(Output.NEW_FILE), TracksOptions())
    assert (plan.finished, plan.cannot, plan.left_out) == ((), (), ())
    (earlier,) = plan.written_earlier
    assert (earlier.paired, earlier.target) == (TURKISH, done.path)


def test_a_result_named_in_another_case_is_written_earlier_too(b: SimpleNamespace) -> None:
    upper = SubtitleFile(Path("Show Name - S01E01_CLEANED.tr.srt"), Language("tur"))
    plan = plan_subtitles(episode(b, paired=(TURKISH, upper)), beside(Output.NEW_FILE), TracksOptions())
    assert (plan.finished, plan.cannot) == ((), ())
    assert [f.paired for f in plan.written_earlier] == [TURKISH]


def test_a_foreign_file_in_the_way_of_a_new_file_is_still_a_problem(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"de": Wanted.WANTED}, output=Output.NEW_FILE)
    item = episode(b, b.subtitle(2), paired=())
    there = SubtitleFile(item.file.path.with_name(f"{item.file.path.stem}.de.srt"), None)
    plan = plan_subtitles(episode(b, b.subtitle(2), paired=(there,)), options, TracksOptions())
    assert plan.written_earlier == ()
    assert [c.cannot for c in plan.cannot] == [(Cannot.TARGET_EXISTS,)]


def test_a_translation_is_written_by_its_language(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"de": Wanted.WANTED}, output=Output.NEW_FILE)
    item = episode(b, b.subtitle(2), paired=())
    (finished,) = plan_subtitles(item, options, TracksOptions()).finished
    assert finished.source is Source.TRANSLATION
    assert finished.target == item.file.path.with_name(f"{item.file.path.stem}.de.srt")


def test_a_translation_over_a_file_that_lies_there_is_a_problem(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(languages={"de": Wanted.WANTED}, output=Output.REPLACE)
    item = episode(b, b.subtitle(2), paired=())
    there = SubtitleFile(item.file.path.with_name(f"{item.file.path.stem}.de.srt"), None)
    # The scan found the file without a language, so German counts as absent.
    plan = plan_subtitles(episode(b, b.subtitle(2), paired=(there,)), options, TracksOptions())
    assert plan.finished == ()
    assert [c.cannot for c in plan.cannot] == [(Cannot.TARGET_EXISTS,)]


def test_a_cleaned_embedded_track_is_written_beside_by_its_language(b: SimpleNamespace) -> None:
    options = replace(CLEAN_HI, languages={"en": Wanted.WANTED}, output=Output.REPLACE)
    item = episode(b, b.subtitle(2), paired=())
    plan = plan_subtitles(item, options, TracksOptions())
    (finished,) = plan.finished
    assert finished.source is Source.EMBEDDED
    assert finished.target == item.file.path.with_name(f"{item.file.path.stem}.en.srt")
    assert plan.into_video == ()


def test_two_embedded_tracks_of_one_language_get_two_names(b: SimpleNamespace) -> None:
    options = replace(CLEAN_HI, languages={"en": Wanted.WANTED}, output=Output.NEW_FILE)
    item = episode(b, b.subtitle(2), b.subtitle(3, hearing_impaired=True), paired=())
    plan = plan_subtitles(item, options, TracksOptions())
    stem = item.file.path.stem
    assert [f.target.name for f in plan.finished if f.target] == [f"{stem}.en.srt", f"{stem}.en.sdh.srt"]
    assert plan.cannot == ()
