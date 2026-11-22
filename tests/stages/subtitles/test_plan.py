from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.subtitles import (
    Approval,
    Cannot,
    Lines,
    Reference,
    ReferenceKind,
    RuleSetUse,
    Source,
    Step,
    StepKind,
    SubtitlesOptions,
    SyncEngine,
    Wanted,
    plan_subtitles,
)
from showrunner.stages.tracks import KindTest, PairedFile, TrackMatch, TrackRule, TracksOptions, Verdict

TURKISH = SubtitleFile(Path("Show Name - S01E01.tr.srt"), Language("tur"))
CLEAN = {"Hearing impaired": RuleSetUse.USED, "Lyrics": RuleSetUse.USED}
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
        Step(StepKind.CLEAN, ("Hearing impaired", "Lyrics")),  # sorted, paused sets left out
        Step(StepKind.SYNC, engine=SyncEngine.ALASS, settings=(("split_penalty", "7"),)),
        Step(StepKind.RESPLIT, model="Sample 9B Instruct"),
    )
    # Sync and re-split work against the English text track.
    assert plan.reference is not None
    assert plan.reference.track == b.subtitle(2)


def test_a_paired_file_the_tracks_do_not_add_gets_no_work(b: SimpleNamespace) -> None:
    options = SubtitlesOptions(cleanup=CLEAN, sync=SyncEngine.FFSUBSYNC)
    assert plan_subtitles(episode(b, b.subtitle(2)), options, TracksOptions()).finished == ()
    # Nor does one the rules drop after adding it.
    drop = TrackRule(match=TrackMatch(kind=KindTest.SUBTITLE, languages=["tr"]), verdict=Verdict.DROP)
    dropped = replace(ADD_TURKISH, rules=[drop])
    assert plan_subtitles(episode(b, b.subtitle(2)), options, dropped).finished == ()


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
        Step(StepKind.TRANSLATE, ("Hearing impaired", "Lyrics")),
        Step(StepKind.CLEAN, ("Hearing impaired", "Lyrics")),
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
