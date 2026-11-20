from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from showrunner.core.language import add_languages
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.track import ObjectAudio
from showrunner.stages.tracks import (
    Flag,
    FlagChange,
    FlagShape,
    FlagTest,
    KindTest,
    PairedFile,
    PlanProblemKind,
    PlanRefused,
    SourceTest,
    TrackMatch,
    TrackPlan,
    TrackRule,
    TracksOptions,
    Verdict,
    describe_track,
    plan_tracks,
)


def options(*rules: TrackRule) -> TracksOptions:
    return TracksOptions(rules=list(rules))


def drop(label: str = "", **match: object) -> TrackRule:
    return TrackRule(label=label, match=TrackMatch(**match), verdict=Verdict.DROP)  # type: ignore[arg-type]


def keep(**match: object) -> TrackRule:
    return TrackRule(match=TrackMatch(**match), verdict=Verdict.KEEP)  # type: ignore[arg-type]


def make_first(flag: str, **match: object) -> TrackRule:
    return TrackRule(match=TrackMatch(**match), **{flag: FlagShape.FIRST})  # type: ignore[arg-type]


def adding(media: MediaItem, chosen: TracksOptions) -> TracksOptions:
    """`chosen` with every paired file of `media` chosen to be added."""
    return replace(chosen, add_paired=[PairedFile.of(subtitle) for subtitle in media.subtitles])


def planned(result: TrackPlan | PlanRefused) -> TrackPlan:
    assert isinstance(result, TrackPlan)
    return result


def kept_ids(plan: TrackPlan) -> list[int]:
    return [k.track.id for k in plan.kept]


def test_a_track_no_rule_matches_is_kept(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.subtitle(2, b.en))
    plan = planned(plan_tracks(media, options(drop(languages=["tr"]))))
    assert kept_ids(plan) == [0, 1, 2]
    assert plan.dropped == ()


def test_drop_by_each_kind_of_match_keeps_the_order_of_the_rest(b: SimpleNamespace) -> None:
    media = b.item(
        b.video(),
        b.audio(1, "A_DTS", b.en, channels=6),
        b.audio(2, "A_AAC", b.en, channels=2),
        b.audio(3, "A_AAC", b.tr, channels=2, name="Commentary"),
        b.subtitle(4, b.en),
    )
    rules = options(
        drop(kind=KindTest.AUDIO, languages=["en"], codecs=["DTS"]),
        drop(kind=KindTest.AUDIO, name="commentary"),
        drop(kind=KindTest.SUBTITLE, languages=["en"]),
    )
    plan = planned(plan_tracks(media, rules))
    assert kept_ids(plan) == [0, 2]
    assert [(d.track.id, d.rule_index) for d in plan.dropped] == [(1, 0), (3, 1), (4, 2)]


def test_the_first_deciding_rule_wins(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.subtitle(2, b.tr), b.subtitle(3, b.en))
    keep_turkish = keep(kind=KindTest.SUBTITLE, languages=["tr"])
    drop_subtitles = drop(kind=KindTest.SUBTITLE)
    plan = planned(plan_tracks(media, options(keep_turkish, drop_subtitles)))
    assert kept_ids(plan) == [0, 1, 2]
    assert [(d.track.id, d.rule_index) for d in plan.dropped] == [(3, 1)]
    # With the order reversed the drop rule decides first, so the keep rule never gets a say.
    plan = planned(plan_tracks(media, options(drop_subtitles, keep_turkish)))
    assert kept_ids(plan) == [0, 1]
    assert {d.rule_index for d in plan.dropped} == {0}


def test_a_pass_rule_leaves_the_decision_to_later_rules(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr))
    flags_only = make_first("default", languages=["en"])
    plan = planned(plan_tracks(media, options(flags_only, drop(languages=["en"]))))
    assert kept_ids(plan) == [0, 2]


def test_a_disabled_rule_is_skipped(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr))
    off = TrackRule(enabled=False, match=TrackMatch(languages=["tr"]), verdict=Verdict.DROP)
    assert kept_ids(planned(plan_tracks(media, options(off)))) == [0, 1, 2]
    plan = planned(plan_tracks(media, options(off, drop(languages=["en"]))))
    assert kept_ids(plan) == [0, 2]
    assert plan.dropped[0].rule_index == 1  # positions count disabled rules too


@pytest.mark.parametrize("rules", [[], [replace(drop(kind=KindTest.AUDIO), enabled=False)], [keep()]])
def test_a_paired_file_not_chosen_is_not_added_whatever_the_rules(b: SimpleNamespace, rules) -> None:
    media = b.item(b.video(), b.audio(1), subtitles=(b.srt(b.tr),))
    plan = planned(plan_tracks(media, TracksOptions(rules=rules)))
    assert kept_ids(plan) == [0, 1]
    assert plan.dropped == ()
    assert not plan.needs_remux


def test_a_chosen_paired_file_is_added_without_any_rule_and_keeps_its_number(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1), subtitles=(b.srt(b.en), b.srt(b.tr), b.srt(b.tr, forced=True)))
    chosen = TracksOptions(add_paired=[PairedFile.of(media.subtitles[1])])
    plan = planned(plan_tracks(media, chosen))
    assert kept_ids(plan) == [0, 1, -2]  # the forced Turkish file is another choice
    assert plan.needs_remux


def test_default_moves_to_the_first_matching_track_of_its_kind(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en, default=True), b.audio(2, language=b.tr))
    plan = planned(plan_tracks(media, options(make_first("default", kind=KindTest.AUDIO, languages=["tr"]))))
    video, english, turkish = plan.kept
    assert english.flag_changes == (FlagChange(Flag.DEFAULT, False),)
    assert turkish.flag_changes == (FlagChange(Flag.DEFAULT, True),)
    assert not english.flags.default
    assert turkish.flags.default
    assert video.flag_changes == ()  # another kind is untouched
    assert not plan.needs_remux


def test_only_the_first_of_several_matches_gets_the_flag(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr), b.audio(3, language=b.tr))
    plan = planned(plan_tracks(media, options(make_first("default", languages=["tr"]))))
    assert [k.flags.default for k in plan.kept[1:]] == [False, True, False]


def test_a_flag_already_in_the_wanted_shape_changes_nothing(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en, default=True), b.audio(2, language=b.tr))
    plan = planned(plan_tracks(media, options(make_first("default", languages=["en"]))))
    assert all(not k.flag_changes for k in plan.kept)


def test_a_rule_that_reaches_no_track_of_a_kind_leaves_that_kind_alone(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en, default=True), b.audio(2, language=b.en))
    plan = planned(plan_tracks(media, options(make_first("default", languages=["tr"]))))
    assert all(not k.flag_changes for k in plan.kept)


def test_later_first_rules_are_fallbacks(b: SimpleNamespace) -> None:
    rules = options(
        make_first("default", kind=KindTest.AUDIO, languages=["tr"]),
        make_first("default", kind=KindTest.AUDIO, languages=["en"]),
    )
    with_turkish = b.item(b.video(), b.audio(1, language=b.en, default=True), b.audio(2, language=b.tr))
    assert [k.flags.default for k in planned(plan_tracks(with_turkish, rules)).kept[1:]] == [False, True]
    without_turkish = b.item(b.video(), b.audio(1), b.audio(2, language=b.en), b.audio(3, language=b.en))
    assert [k.flags.default for k in planned(plan_tracks(without_turkish, rules)).kept[1:]] == [False, True, False]


def test_a_dropped_track_cannot_get_the_flag(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.tr, name="First"), b.audio(2, language=b.tr))
    rules = options(drop(kind=KindTest.AUDIO, name="first"), make_first("default", languages=["tr"]))
    plan = planned(plan_tracks(media, rules))
    assert kept_ids(plan) == [0, 2]
    assert plan.kept[1].flags.default


def test_forced_has_the_same_shape(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1), b.subtitle(2, b.en, forced=True), b.subtitle(3, b.tr))
    plan = planned(plan_tracks(media, options(make_first("forced", kind=KindTest.SUBTITLE, languages=["tr"]))))
    assert plan.kept[2].flag_changes == (FlagChange(Flag.FORCED, False),)
    assert plan.kept[3].flag_changes == (FlagChange(Flag.FORCED, True),)


def test_default_and_forced_are_decided_separately(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1), b.subtitle(2, b.en, default=True), b.subtitle(3, b.tr))
    rules = options(
        make_first("default", kind=KindTest.SUBTITLE, languages=["tr"]),
        make_first("forced", kind=KindTest.SUBTITLE, languages=["en"]),
    )
    english, turkish = planned(plan_tracks(media, rules)).kept[2:]
    assert (english.flags.default, english.flags.forced) == (False, True)
    assert (turkish.flags.default, turkish.flags.forced) == (True, False)


def test_make_the_turkish_external_subtitle_default(b: SimpleNamespace) -> None:
    media = b.item(
        b.video(),
        b.audio(1, language=b.en, default=True),
        b.subtitle(2, b.en, default=True),
        subtitles=(b.srt(b.en), b.srt(b.tr)),
    )
    rules = options(make_first("default", kind=KindTest.SUBTITLE, languages=["tr"]))
    plan = planned(plan_tracks(media, adding(media, rules)))
    assert [k.flags.default for k in plan.kept] == [False, True, False, False, True]
    turkish = plan.kept[-1]
    assert turkish.external == media.subtitles[1]
    assert turkish.track.id < 0
    assert plan.needs_remux


def test_external_subtitles_are_matched_like_tracks(b: SimpleNamespace) -> None:
    media = b.item(
        b.video(),
        b.audio(1),
        subtitles=(b.srt(b.en), b.srt(b.tr), b.srt(b.tr, forced=True), b.srt(None), b.srt(b.en, sdh=True)),
    )
    rules = options(
        drop(kind=KindTest.SUBTITLE, languages=["en"], hearing_impaired=FlagTest.SET),
        drop(kind=KindTest.SUBTITLE, languages=["und"]),
        drop(codecs=["SubRip"], forced=FlagTest.SET),
    )
    plan = planned(plan_tracks(media, adding(media, rules)))
    assert {(d.external.path.name, d.rule_index) for d in plan.dropped if d.external} == {
        ("Show Name - S01E01.en.sdh.srt", 0),
        ("Show Name - S01E01.srt", 1),
        ("Show Name - S01E01.tr.forced.srt", 2),
    }
    assert [k.external.path.name for k in plan.kept if k.external] == [
        "Show Name - S01E01.en.srt",
        "Show Name - S01E01.tr.srt",
    ]


def test_a_chosen_external_subtitle_is_added_after_the_tracks(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1), b.subtitle(2, b.en), subtitles=(b.srt(b.tr),))
    plan = planned(plan_tracks(media, adding(media, options())))
    assert kept_ids(plan) == [0, 1, 2, -1]
    assert [k.external is not None for k in plan.kept] == [False, False, False, True]
    added = plan.kept[-1].track
    assert added.codec == "S_TEXT/UTF8"
    assert added.subtitle is not None
    assert added.subtitle.text_based


def test_an_image_subtitle_file_is_not_text_based(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1), subtitles=(SubtitleFile(Path("Show Name - S01E01.sup"), b.en),))
    track = planned(plan_tracks(media, adding(media, options()))).kept[-1].track
    assert track.subtitle is not None
    assert not track.subtitle.text_based
    assert track.codec == "S_HDMV/PGS"


def test_external_flags_come_from_the_file(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1), subtitles=(b.srt(b.en, forced=True, sdh=True),))
    flags = planned(plan_tracks(media, adding(media, options()))).kept[-1].flags
    assert flags.forced
    assert flags.hearing_impaired
    assert not flags.default


def test_needs_remux(b: SimpleNamespace) -> None:
    base = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr))
    assert not planned(plan_tracks(base, options())).needs_remux
    # Header edits only.
    assert not planned(plan_tracks(base, options(make_first("default", languages=["tr"])))).needs_remux
    # A dropped track.
    assert planned(plan_tracks(base, options(drop(languages=["en"])))).needs_remux
    # An added subtitle file.
    with_file = b.item(b.video(), b.audio(1), subtitles=(b.srt(b.tr),))
    assert planned(plan_tracks(with_file, adding(with_file, options()))).needs_remux


def test_a_subtitle_file_left_out_needs_no_remux(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1), subtitles=(b.srt(b.en),))
    plan = planned(plan_tracks(media, adding(media, options(drop(kind=KindTest.SUBTITLE)))))
    assert [d.external is not None for d in plan.dropped] == [True]
    assert not plan.needs_remux


def test_no_plan_when_every_video_track_would_go(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1))
    result = plan_tracks(media, options(drop("no video", kind=KindTest.VIDEO)))
    assert isinstance(result, PlanRefused)
    (problem,) = result.problems
    assert problem.kind is PlanProblemKind.NO_VIDEO_LEFT
    assert [d.track.id for d in problem.dropped] == [0]
    assert problem.dropped[0].rule.label == "no video"


def test_no_plan_when_every_audio_track_would_go(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr))
    result = plan_tracks(media, options(drop(kind=KindTest.AUDIO)))
    assert isinstance(result, PlanRefused)
    (problem,) = result.problems
    assert problem.kind is PlanProblemKind.NO_AUDIO_LEFT
    assert [d.track.id for d in problem.dropped] == [1, 2]


def test_both_guards_are_reported_together(b: SimpleNamespace) -> None:
    result = plan_tracks(b.item(b.video(), b.audio(1)), options(drop()))
    assert isinstance(result, PlanRefused)
    assert {p.kind for p in result.problems} == {PlanProblemKind.NO_VIDEO_LEFT, PlanProblemKind.NO_AUDIO_LEFT}


def test_dropping_part_of_a_kind_or_a_kind_the_file_never_had_is_fine(b: SimpleNamespace) -> None:
    assert isinstance(plan_tracks(b.item(b.video()), options(drop(kind=KindTest.SUBTITLE))), TrackPlan)
    two_audio = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr))
    assert isinstance(plan_tracks(two_audio, options(drop(languages=["en"]))), TrackPlan)


def test_describe_track_uses_the_naming_names(b: SimpleNamespace) -> None:
    track = b.audio(1, "A_EAC3", b.en, channels=6, object_audio=ObjectAudio.ATMOS)
    assert describe_track(track) == "audio Dolby Digital Plus with Dolby Atmos 5.1 English"
    assert describe_track(b.subtitle(2)) == "subtitle SubRip"
    assert describe_track(b.audio(3, "A_UNKNOWN", channels=None)) == "audio A_UNKNOWN"


@pytest.mark.parametrize(("source", "left"), [(SourceTest.EMBEDDED, [0, -1]), (SourceTest.PAIRED, [0, 2])])
def test_a_rule_drops_a_subtitle_by_where_it_comes_from(
    b: SimpleNamespace, source: SourceTest, left: list[int]
) -> None:
    media = b.item(b.video(), b.subtitle(2, b.tr), subtitles=(b.srt(b.tr),))
    drop = TrackRule(match=TrackMatch(kind=KindTest.SUBTITLE, languages=["tr"], source=source), verdict=Verdict.DROP)
    plan = planned(plan_tracks(media, adding(media, options(drop))))
    assert kept_ids(plan) == left


def test_the_same_item_and_options_give_the_last_plan_again_and_other_options_a_new_one(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr))
    chosen = options(drop(languages=["tr"]))
    first = plan_tracks(media, chosen)
    # The stages of one file's plan ask again with the same objects: the plan is not made again.
    assert plan_tracks(media, chosen) is first
    # Equal options in another object, and other options, are planned anew.
    again = plan_tracks(media, replace(chosen))
    assert again is not first
    assert again == first
    assert kept_ids(planned(plan_tracks(media, options(drop(languages=["en"]))))) == [0, 2]


def test_a_plan_is_made_again_once_other_languages_are_known(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en))
    chosen = options(drop(languages=["roa"]))
    first = plan_tracks(media, chosen)
    # A code the rule names may mean a language only once a program has listed it.
    add_languages({"roa": "Romance languages"})
    try:
        assert plan_tracks(media, chosen) is not first
    finally:
        add_languages({})
