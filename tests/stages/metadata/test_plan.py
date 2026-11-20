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
    language_after,
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
        (Property.NAME, 1, "AC-3 5.1", "Show.Name.(Dolby.Digital)"),
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


def language_rule(tag: str, **match) -> TrackRule:
    return TrackRule(match=TrackMatch(**match), language=tag, from_choice=True)


def test_a_rule_gives_its_tag_to_the_tracks_it_fits_and_to_no_others(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, language="eng"), b.audio(2, language="tur"), b.subtitle(3, language="eng"))
    tracks = rules(language_rule("es-419", kind=KindTest.AUDIO, languages=["en"]))
    assert changes(plan(item, MetadataOptions(), NO_NAMES, tracks)) == [(Property.LANGUAGE, 1, "en", "es-419")]


def test_a_rule_also_gives_a_language_to_a_track_without_one_and_wins_over_the_untagged_choice(
    b: SimpleNamespace,
) -> None:
    item = b.item(b.audio(0, language=None), b.audio(1, "Special", language=None))
    tracks = rules(language_rule("sr-Latn-RS", name="Special"))
    result = plan(item, MetadataOptions(untagged_language="pt-BR"), NO_NAMES, tracks)
    assert changes(result) == [(Property.LANGUAGE, 0, "", "pt-BR"), (Property.LANGUAGE, 1, "", "sr-Latn-RS")]


def test_a_rule_that_gives_what_the_track_has_changes_nothing(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, language="por"))
    assert changes(plan(item, MetadataOptions(), NO_NAMES, rules(language_rule("pt")))) == []
    assert changes(plan(item, MetadataOptions(), NO_NAMES, rules(language_rule("pt-BR")))) == [
        (Property.LANGUAGE, 0, "pt", "pt-BR")
    ]


def test_the_first_rule_that_sets_a_language_decides_and_a_paused_one_does_not(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, language="eng"))
    paused = replace(language_rule("fr"), enabled=False)
    tracks = rules(paused, language_rule("de"), language_rule("es"))
    assert changes(plan(item, MetadataOptions(), NO_NAMES, tracks)) == [(Property.LANGUAGE, 0, "en", "de")]


def test_a_rule_sets_the_language_whatever_it_decides_about_keeping(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, language="eng"), b.audio(1, language="tur"))
    kept = TrackRule(match=TrackMatch(languages=["tur"]), verdict=Verdict.KEEP, language="de")
    dropping = TrackRule(match=TrackMatch(languages=["eng"]), verdict=Verdict.DROP, language="fr")
    result = plan(item, MetadataOptions(), NO_NAMES, rules(kept, dropping))
    # The dropped track is not in the new file, so it gets nothing.
    assert changes(result) == [(Property.LANGUAGE, 1, "tr", "de")]


def test_a_rule_that_is_not_a_language_refuses_the_plan(b: SimpleNamespace) -> None:
    item = b.item(b.audio(0, language="eng"), b.audio(1, language="eng"))
    result = plan(item, MetadataOptions(), NO_NAMES, rules(language_rule("xx-1")))
    assert isinstance(result, MetadataRefused)
    assert [(p.kind, p.detail) for p in result.problems] == [(MetadataProblemKind.INVALID_LANGUAGE, "xx-1")]


def test_a_rule_for_en_reaches_the_en_us_tracks_too(b: SimpleNamespace) -> None:
    # A known limit of a chip's rule: a tag without a region fits every region of the language.
    item = b.item(b.audio(0, language="eng"), b.audio(1, language="en-US"))
    result = plan(item, MetadataOptions(), NO_NAMES, rules(language_rule("de", languages=["en"])))
    assert changes(result) == [(Property.LANGUAGE, 0, "en", "de"), (Property.LANGUAGE, 1, "en-US", "de")]
    # A rule for the region alone reaches that region alone.
    result = plan(item, MetadataOptions(), NO_NAMES, rules(language_rule("de", languages=["en-US"])))
    assert changes(result) == [(Property.LANGUAGE, 1, "en-US", "de")]


def test_a_refused_track_plan_still_gets_the_languages(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, language="eng"))
    tracks = rules(drop(kind=KindTest.AUDIO), language_rule("de"))
    # A rule for every kind reaches the video track too.
    assert changes(plan(item, MetadataOptions(), NO_NAMES, tracks)) == [
        (Property.LANGUAGE, 0, "", "de"),
        (Property.LANGUAGE, 1, "en", "de"),
    ]


def test_a_video_rule_gives_the_video_track_its_language_and_the_untagged_one_does_not(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, language=None))
    tracks = rules(language_rule("ja", kind=KindTest.VIDEO))
    options = MetadataOptions(untagged_language="pt-BR")
    assert changes(plan(item, options, NO_NAMES, tracks)) == [
        (Property.LANGUAGE, 0, "", "ja"),
        (Property.LANGUAGE, 1, "", "pt-BR"),
    ]
    assert language_after(item.file.tracks[0], tracks.rules, True, "pt-BR") == "ja"
    assert language_after(item.file.tracks[0], [], True, "pt-BR") == ""


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


def test_a_template_names_the_language_the_track_gets_not_the_one_it_has(b: SimpleNamespace) -> None:
    naming = replace(NO_NAMES, audio_track_template="{language} ({language_code})")
    item = b.item(b.audio(0, language="eng"), b.audio(1, language=None))
    tracks = rules(language_rule("de", languages=["en"]))
    result = plan(item, MetadataOptions(untagged_language="pt-BR"), naming, tracks)
    assert changes(result) == [
        (Property.NAME, 0, "", "German (de)"),
        (Property.LANGUAGE, 0, "en", "de"),
        (Property.NAME, 1, "", "Portuguese (pt-BR)"),
        (Property.LANGUAGE, 1, "", "pt-BR"),
    ]
    # With nothing to change the track's own language is named.
    assert changes(plan(item, MetadataOptions(), naming, NO_RULES)) == [(Property.NAME, 0, "", "English (en)")]


def test_the_language_a_plan_gives_is_what_the_names_place_reads(b: SimpleNamespace) -> None:
    audio, untagged, video = b.audio(0, language="eng"), b.audio(1, language=None), b.video(2)
    rule = [language_rule("de", languages=["en"])]
    assert language_after(audio, rule, True) == "de"
    assert language_after(untagged, rule, True) == ""
    assert language_after(untagged, rule, True, "pt-BR") == "pt-BR"
    assert language_after(audio, [], True, "pt-BR") == ""  # it has a language: the untagged choice does not apply
    assert language_after(video, rule, True, "pt-BR") == ""


# --- {file_title} ---

TRACKS_WITH_TITLE = {
    "video_track_template": "{file_title} {resolution}",
    "audio_track_template": "{file_title} {codec}",
    "subtitle_track_template": "{file_title} {language}",
}


def test_a_track_name_copies_the_title_the_title_template_makes(episode) -> None:
    naming = NamingOptions(title_template="{show} - {episode_code}", **TRACKS_WITH_TITLE)
    assert changes(plan(episode, naming=naming)) == [
        (Property.TITLE, None, "Old Title", "Show Name - S01E01"),
        (Property.NAME, 0, "", "Show Name - S01E01 1080p"),
        (Property.NAME, 1, "AC-3 5.1", "Show Name - S01E01 Dolby Digital"),
        (Property.NAME, 2, "English", "Show Name - S01E01 English"),
    ]


def test_a_track_name_copies_the_title_the_file_has_when_the_title_template_is_empty_or_gives_nothing(episode) -> None:
    for title_template in ("", "{episode_title}"):
        naming = NamingOptions(title_template=title_template, audio_track_template="{file_title} {codec}")
        assert changes(plan(episode, naming=naming)) == [(Property.NAME, 1, "AC-3 5.1", "Old Title Dolby Digital")]


def test_the_title_in_a_track_name_is_copied_as_it_is_and_the_rest_takes_the_track_templates_join_choice(
    episode,
) -> None:
    naming = NamingOptions(
        title_template="{show} - {episode_code}",
        audio_track_template="{file_title} {codec}",
        audio_track_space=SpaceStyle.DOT,
        title_space=SpaceStyle.UNDERSCORE,
    )
    # The title is made with its own choice and copied unchanged; the track template joins its own gap and the
    # spaces inside its other tokens.
    assert changes(plan(episode, naming=naming))[1:] == [
        (Property.NAME, 1, "AC-3 5.1", "Show_Name_-_S01E01.Dolby.Digital")
    ]


def test_a_file_without_a_title_gives_a_track_name_without_it(b: SimpleNamespace) -> None:
    item = b.item(b.audio(1, "AC-3 5.1"), title="")
    naming = NamingOptions(audio_track_template="[{file_title} ]{codec}")
    assert changes(plan(item, naming=naming)) == [(Property.NAME, 1, "AC-3 5.1", "Dolby Digital")]


def test_the_title_template_refuses_file_title(episode) -> None:
    result = plan(episode, naming=NamingOptions(title_template="{file_title}"))
    assert isinstance(result, MetadataRefused)
    (problem,) = result.problems
    assert (problem.template, [p.kind for p in problem.template_problems]) == ("title_template", [ProblemKind.NOT_HERE])


def test_file_title_equals_the_planned_title_with_its_own_join_choice_and_replacements(episode) -> None:
    naming = NamingOptions(
        title_template="{show} {episode_code} - done",
        audio_track_template="{file_title}",
        title_space=SpaceStyle.DOT,
        value_maps={"show": {"Show Name": "Other Name"}},
    )
    (_, _, _, title), (_, _, _, name) = changes(plan(episode, naming=naming))
    assert title == "Other Name.S01E01.-.done"  # a replacement is written as typed
    assert name == title
