"""Counting the changes of a file's plans per group."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from showrunner.app.jobs.counts import count_changes, track_changes
from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.stages import MetadataStage, TracksStage
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackFlags, TrackKind, VideoProperties
from showrunner.stages.tracks import (
    FlagShape,
    KindTest,
    TrackMatch,
    TrackPlan,
    TrackRule,
    TracksOptions,
    Verdict,
    plan_tracks,
)
from showrunner.tools.probe import Programs

STAGES = (TracksStage(), MetadataStage(Path("mkvpropedit"), Programs()))
TRACKS = (
    Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080)),
    Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), "English", TrackFlags(default=True), audio=AudioProperties(6)),
    Track(2, TrackKind.AUDIO, "A_AC3", Language("tur"), "Turkish", audio=AudioProperties(6)),
    Track(3, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("tur"), "Turkish", subtitle=SubtitleProperties()),
)
ITEM = MediaItem(Movie("Movie Title", 2016), MediaFile(Path("Movie Title (2016).mkv"), "matroska", tracks=TRACKS))


def rules(*rules: TrackRule) -> TracksOptions:
    return TracksOptions(rules=list(rules))


def track_plan(options: TracksOptions) -> TrackPlan:
    result = plan_tracks(ITEM, options)
    assert isinstance(result, TrackPlan)
    return result


def in_language(kind: KindTest, language: str, **action: object) -> TrackRule:
    return TrackRule(match=TrackMatch(kind=kind, languages=[language]), **action)  # type: ignore[arg-type]


def test_a_default_that_moves_is_one_change_per_kind() -> None:
    assert track_changes(track_plan(rules())) == 0
    turkish_audio = in_language(KindTest.AUDIO, "tr", default=FlagShape.FIRST)
    assert track_changes(track_plan(rules(turkish_audio))) == 1
    turkish_subtitles = in_language(KindTest.SUBTITLE, "tr", default=FlagShape.FIRST, forced=FlagShape.FIRST)
    assert track_changes(track_plan(rules(turkish_audio, turkish_subtitles))) == 3
    # The default staying where it is changes nothing.
    assert track_changes(track_plan(rules(in_language(KindTest.AUDIO, "en", default=FlagShape.FIRST)))) == 0


def test_a_new_file_is_one_change_and_a_dropped_default_moves_nothing_by_itself() -> None:
    drop_english = in_language(KindTest.AUDIO, "en", verdict=Verdict.DROP)
    # The default track goes; no track of the kind has the flag after, which is a change of that flag too.
    assert track_changes(track_plan(rules(drop_english))) == 2
    drop_subtitles = in_language(KindTest.SUBTITLE, "tr", verdict=Verdict.DROP)
    assert track_changes(track_plan(rules(drop_subtitles))) == 1


def test_names_count_apart_from_the_flags_the_rules_move(profile: Profile) -> None:
    turkish_audio = in_language(KindTest.AUDIO, "tr", default=FlagShape.FIRST)
    naming = replace(
        profile.for_stage("naming"),
        title_template="{title}",
        video_track_template="",
        audio_track_template="Audio",
        subtitle_track_template="",
    )
    planned = profile.with_options("tracks", rules(turkish_audio)).with_options("naming", naming)
    (file,) = preview([ITEM], planned, STAGES, stamped=False).files
    # The title and two track names; the default moving to Turkish audio, written in place, is a track change.
    assert count_changes(file) == {ChangeGroup.TRACKS: 1, ChangeGroup.NAMES: 3}


def test_a_refused_plan_counts_nothing(profile: Profile) -> None:
    drop_audio = TrackRule(match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.DROP)
    (file,) = preview([ITEM], profile.with_options("tracks", rules(drop_audio)), STAGES, stamped=False).files
    assert count_changes(file)[ChangeGroup.TRACKS] == 0


def test_a_forced_flag_a_name_implies_counts_as_a_name_change(profile: Profile) -> None:
    named = Track(4, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), "Forced", subtitle=SubtitleProperties())
    item = replace(ITEM, file=replace(ITEM.file, tracks=(*TRACKS, named)))
    naming = replace(
        profile.for_stage("naming"),
        title_template="",
        video_track_template="",
        audio_track_template="",
        subtitle_track_template="",
    )
    implied = replace(profile.for_stage("metadata"), write_implied_flags=True)
    planned = profile.with_options("naming", naming).with_options("metadata", implied)
    (file,) = preview([item], planned, STAGES, stamped=False).files
    assert count_changes(file) == {ChangeGroup.TRACKS: 0, ChangeGroup.NAMES: 1}


def test_a_new_order_is_one_change_beside_the_new_file() -> None:
    order = [TrackMatch(kind=KindTest.AUDIO, languages=["tr"])]
    plan = plan_tracks(ITEM, TracksOptions(order=order))
    assert isinstance(plan, TrackPlan)
    assert track_changes(plan) == 2  # the new file and its order
    # The default stays on the English track wherever it stands.
    assert [k.track.id for k in plan.kept if k.flags.default] == [1]
