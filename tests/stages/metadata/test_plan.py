from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from showrunner.core.media import SubtitleFile
from showrunner.core.naming import SUGGESTED_TEMPLATES, EpisodeCodeFormat, NamingOptions, ProblemKind, SpaceStyle
from showrunner.stages.metadata import (
    HeaderChange,
    MetadataOptions,
    MetadataPlan,
    MetadataProblemKind,
    MetadataRefused,
    plan_metadata,
)
from showrunner.stages.tracks import FlagShape, KindTest, PairedFile, TrackMatch, TrackRule, TracksOptions, Verdict
from showrunner.tools.mkvtoolnix.propedit import Property

NO_RULES = TracksOptions()
SOURCE = "WEB-DL"
IMPLIED = MetadataOptions(write_implied_flags=True)
NO_NAMES = NamingOptions()
SUGGESTED = NamingOptions(**SUGGESTED_TEMPLATES)


def plan(item, options=None, naming=None, tracks=NO_RULES):
    return plan_metadata(item, options or MetadataOptions(), naming or SUGGESTED, tracks, source=SOURCE)


def changes(result) -> list[tuple]:
    assert isinstance(result, MetadataPlan), result
    return [(c.prop, c.track_id, c.old, c.new) for c in result.changes]


def rules(*rule: TrackRule) -> TracksOptions:
    return TracksOptions(rules=list(rule))


def first(kind: KindTest, flag: str, **match) -> TrackRule:
    return TrackRule(match=TrackMatch(kind=kind, **match), **{flag: FlagShape.FIRST})


def drop(**match) -> TrackRule:
    return TrackRule(verdict=Verdict.DROP, match=TrackMatch(**match))


@pytest.fixture
def episode(b: SimpleNamespace):
    return b.item(b.video(0), b.audio(1, "AC-3 5.1"), b.subtitle(2, "English"), title="Old Title")


# --- title and names ---


def test_the_suggested_templates_set_the_title_and_every_track_name(episode) -> None:
    assert changes(plan(episode)) == [
        (Property.TITLE, None, "Old Title", "Show Name - S01E01"),
        (Property.NAME, 0, "", "Show Name - S01E01 (1080p WEB-DL)"),
        (Property.NAME, 1, "AC-3 5.1", "Show Name - S01E01 (Dolby Digital 5.1)"),
        (Property.NAME, 2, "English", "Show Name - S01E01"),
    ]


def test_a_value_the_file_already_has_is_not_a_change(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, "Show Name - S01E01 (Dolby Digital 5.1)"), title="Show Name - S01E01")
    assert changes(plan(item)) == []


def test_a_template_that_renders_nothing_leaves_the_title_alone(episode) -> None:
    result = plan(episode, naming=NamingOptions(title_template="{episode_title}"))
    assert not [c for c in result.changes if c.prop is Property.TITLE]


def test_custom_templates_are_used(episode) -> None:
    naming = NamingOptions(title_template="{show} {season:00}x{episode:00}", audio_track_template="{codec}")
    result = changes(plan(episode, naming=naming))
    assert result[0] == (Property.TITLE, None, "Old Title", "Show Name 01x01")
    assert (Property.NAME, 1, "AC-3 5.1", "Dolby Digital") in result


def test_each_template_has_its_own_space_choice_and_the_episode_code_its_format(episode) -> None:
    naming = NamingOptions(
        title_template="{show} {episode_code}",
        audio_track_template="{show} ({codec})",
        video_track_template="{show}",
        audio_track_space=SpaceStyle.DOT,
        video_track_space=SpaceStyle.UNDERSCORE,
        episode_code_format=EpisodeCodeFormat.CROSS,
    )
    assert changes(plan(episode, naming=naming)) == [
        (Property.TITLE, None, "Old Title", "Show Name 1x01"),
        (Property.NAME, 0, "", "Show_Name"),
        (Property.NAME, 1, "AC-3 5.1", "Show.Name (Dolby.Digital)"),
    ]


@pytest.mark.parametrize(
    ("naming", "left"),
    [
        (replace(SUGGESTED, title_template=""), {Property.NAME}),
        (replace(NO_NAMES, title_template="{file_name}"), {Property.TITLE}),
        (NO_NAMES, set()),
    ],
)
def test_an_empty_template_leaves_its_part_as_it_is(episode, naming, left) -> None:
    result = plan(episode, naming=naming)
    assert {c.prop for c in result.changes} == left


# --- languages ---


def test_a_language_is_written_to_audio_and_subtitle_tracks_without_one(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, language=None), b.audio(2, language="eng"), b.subtitle(3, language=None))
    options = MetadataOptions(untagged_language="pt-BR")
    assert changes(plan(item, options, NO_NAMES)) == [
        (Property.LANGUAGE, 1, "", "pt-BR"),
        (Property.LANGUAGE, 3, "", "pt-BR"),
    ]


def test_no_language_is_written_unless_one_is_chosen(b: SimpleNamespace) -> None:
    assert changes(plan(b.item(b.audio(0, language=None)), IMPLIED, NO_NAMES)) == []


# --- flags ---


def test_the_flags_a_name_implies_are_written(b: SimpleNamespace) -> None:
    item = b.item(
        b.audio(0, "Director Commentary"),
        b.subtitle(1, "English SDH"),
        b.subtitle(2, "English forced"),
        b.subtitle(3, "English", hearing_impaired=True),
        b.subtitle(4, "SDH", hearing_impaired=True),
    )
    assert changes(plan(item, IMPLIED, NO_NAMES)) == [
        (Property.FLAG_COMMENTARY, 0, False, True),
        (Property.FLAG_HEARING_IMPAIRED, 1, False, True),
        (Property.FLAG_FORCED, 2, False, True),
    ]


def test_implied_flags_are_not_written_unless_asked_for(b: SimpleNamespace) -> None:
    assert changes(plan(b.item(b.subtitle(0, "English SDH")), MetadataOptions(), NO_NAMES)) == []


def test_implied_flags_come_from_the_name_the_file_has_now(b: SimpleNamespace) -> None:
    # The suggested template replaces "English SDH", so the flag has to be read before that.
    result = changes(plan(b.item(b.subtitle(0, "English SDH")), IMPLIED))
    assert (Property.FLAG_HEARING_IMPAIRED, 0, False, True) in result
    assert (Property.NAME, 0, "English SDH", "Show Name - S01E01 (SDH)") in result


def test_a_renamed_track_plans_nothing_more(b: SimpleNamespace) -> None:
    # Resuming a job counts a step as done when its plan made again on the edited file is empty.
    renamed = b.subtitle(0, "Show Name - S01E01 (SDH)", hearing_impaired=True)
    assert changes(plan(b.item(renamed, title="Show Name - S01E01"), IMPLIED)) == []


def test_a_forced_flag_the_rules_assign_is_not_added_to_by_names(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1), b.subtitle(2, "English"), b.subtitle(3, "English forced"))
    result = plan(item, IMPLIED, NO_NAMES, tracks=rules(first(KindTest.SUBTITLE, "forced", languages=["en"])))
    assert changes(result) == [(Property.FLAG_FORCED, 2, False, True)]


def test_default_changes_of_the_track_rules_are_header_edits_when_no_remux_is_needed(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, "A", language="eng", default=True), b.audio(1, "B", language="tur"))
    result = plan(item, IMPLIED, NO_NAMES, tracks=rules(first(KindTest.AUDIO, "default", languages=["tr"])))
    assert not result.needs_remux
    assert changes(result) == [(Property.FLAG_DEFAULT, 0, True, False), (Property.FLAG_DEFAULT, 1, False, True)]


def test_a_remux_carries_the_track_rules_flags_and_the_plan_says_so(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, "A", language="eng", default=True), b.audio(2, "B", language="tur"))
    tracks = rules(first(KindTest.AUDIO, "default", languages=["tr"]), drop(languages=["en"]))
    result = plan(item, naming=replace(SUGGESTED, title_template=""), tracks=tracks)
    assert result.needs_remux
    # The dropped track gets nothing, and the flags are the track plan's to write.
    assert changes(result) == [
        (Property.NAME, 0, "", "Show Name - S01E01 (1080p WEB-DL)"),
        (Property.NAME, 2, "B", "Show Name - S01E01 (Dolby Digital 5.1)"),
    ]


def test_a_subtitle_file_that_is_added_is_named_under_its_stand_in_id_for_the_remux(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, "A"), subtitles=(SubtitleFile(Path("Show Name - S01E01.tr.srt"), None),))
    added = TracksOptions(add_paired=[PairedFile.of(item.subtitles[0])])
    result = plan(item, MetadataOptions(untagged_language="tr"), replace(SUGGESTED, title_template=""), added)
    assert result.needs_remux
    assert changes(result) == [
        (Property.NAME, 0, "A", "Show Name - S01E01 (Dolby Digital 5.1)"),
        (Property.NAME, -1, "", "Show Name - S01E01"),
        (Property.LANGUAGE, -1, "", "tr"),
    ]


def test_a_paired_file_not_chosen_is_not_added_even_with_a_rule_on(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, "A"), subtitles=(SubtitleFile(Path("Show Name - S01E01.tr.srt"), None),))
    assert not plan(item).needs_remux
    assert not plan(item, tracks=rules(TrackRule(verdict=Verdict.KEEP))).needs_remux


# --- problems ---


def test_a_file_whose_ids_did_not_come_from_mkvmerge_is_refused(b: SimpleNamespace) -> None:
    result = plan(b.item(b.audio(0), ids_from_mkvmerge=False))
    assert isinstance(result, MetadataRefused)
    assert [p.kind for p in result.problems] == [MetadataProblemKind.IDS_NOT_FROM_MKVMERGE]


def test_a_file_that_is_not_matroska_is_refused(b: SimpleNamespace) -> None:
    result = plan(b.item(b.audio(0), container="QuickTime/MP4"))
    assert [(p.kind, p.detail) for p in result.problems] == [(MetadataProblemKind.NOT_MATROSKA, "QuickTime/MP4")]


def test_a_file_the_options_ask_nothing_of_is_not_refused(b: SimpleNamespace) -> None:
    result = plan(b.item(b.audio(0), ids_from_mkvmerge=False, container="AVI"), naming=NO_NAMES)
    assert result == MetadataPlan(Path("Show Name - S01E01.mkv"), ())


def test_a_refused_track_plan_leaves_the_tracks_as_they_are_and_names_them(b: SimpleNamespace) -> None:
    # The rules would drop the only audio track and move the default flag; the file keeps both as they are.
    tracks = rules(drop(kind=KindTest.AUDIO), TrackRule(match=TrackMatch(kind=KindTest.VIDEO), default=FlagShape.FIRST))
    result = plan(b.item(b.video(0), b.audio(1)), tracks=tracks)
    assert isinstance(result, MetadataPlan)
    assert not result.needs_remux
    assert [c.prop for c in result.changes] == [Property.TITLE, Property.NAME, Property.NAME]


def test_template_problems_are_reported_once_instead_of_changes(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1), b.audio(2), b.subtitle(3))
    naming = NamingOptions(audio_track_template="{nope}", subtitle_track_template="{file_name")
    result = plan(item, naming=naming)
    assert isinstance(result, MetadataRefused)
    assert [(p.kind, p.template) for p in result.problems] == [
        (MetadataProblemKind.TEMPLATE, "audio_track_template"),
        (MetadataProblemKind.TEMPLATE, "subtitle_track_template"),
    ]
    assert [p.kind for p in result.problems[0].template_problems] == [ProblemKind.UNKNOWN_TOKEN]


def test_a_template_for_a_kind_the_file_lacks_is_not_checked(b: SimpleNamespace) -> None:
    naming = NamingOptions(subtitle_track_template="{nope}")
    assert isinstance(plan(b.item(b.audio(0)), naming=naming), MetadataPlan)


def test_a_language_that_is_not_one_is_reported(b: SimpleNamespace) -> None:
    result = plan(b.item(b.audio(0)), replace(MetadataOptions(), untagged_language="not a language"))
    assert [(p.kind, p.detail) for p in result.problems] == [(MetadataProblemKind.INVALID_LANGUAGE, "not a language")]


def test_a_language_that_is_not_one_refuses_even_a_file_with_nothing_else_to_change(b: SimpleNamespace) -> None:
    result = plan(b.item(b.audio(0, language="eng")), MetadataOptions(untagged_language="xx1"), NO_NAMES)
    assert isinstance(result, MetadataRefused)
    assert [p.kind for p in result.problems] == [MetadataProblemKind.INVALID_LANGUAGE]


def test_every_problem_is_listed(b: SimpleNamespace) -> None:
    result = plan(b.item(b.audio(0), ids_from_mkvmerge=False, container="AVI"))
    assert [p.kind for p in result.problems] == [
        MetadataProblemKind.IDS_NOT_FROM_MKVMERGE,
        MetadataProblemKind.NOT_MATROSKA,
    ]


def test_a_change_gives_the_edit_the_adapter_needs() -> None:
    edit = HeaderChange(Property.FLAG_FORCED, False, True, 4).edit
    assert (edit.prop, edit.value, edit.track_id) == (Property.FLAG_FORCED, True, 4)
