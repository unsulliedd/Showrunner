from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from showrunner.core.media import Episode, MediaItem
from showrunner.core.naming import (
    TOKENS,
    CustomKind,
    CustomToken,
    EpisodeCodeFormat,
    NamingContext,
    NamingOptions,
    PatternSource,
    SpaceStyle,
    episode_code,
    preview,
)
from showrunner.core.options.serialization import from_sparse, to_sparse

MakeItem = Callable[..., MediaItem]


def spaced(template: str, context: NamingContext, style: SpaceStyle) -> str:
    return preview(template, replace(context, space=style)).text


# What every space becomes: the choice reaches the values and the typed spaces, not other typed characters


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        (SpaceStyle.SPACE, "Show Name (Dolby Digital Plus)"),
        (SpaceStyle.DOT, "Show.Name.(Dolby.Digital.Plus)"),
        (SpaceStyle.UNDERSCORE, "Show_Name_(Dolby_Digital_Plus)"),
        (SpaceStyle.DASH, "Show-Name-(Dolby-Digital-Plus)"),
    ],
)
def test_a_space_inside_a_value_becomes_the_choice(
    episode_context: NamingContext, style: SpaceStyle, expected: str
) -> None:
    track_context = replace(episode_context, track=episode_context.item.file.audio_tracks[0])
    assert spaced("{show} ({codec})", track_context, style) == expected


def test_typed_characters_other_than_spaces_stay_as_typed(episode_context: NamingContext) -> None:
    assert spaced("{show} - {episode_title}", episode_context, SpaceStyle.DOT) == "Show.Name.-.Episode.Name"
    assert spaced("{show}x{episode_title}", episode_context, SpaceStyle.DOT) == "Show.NamexEpisode.Name"
    assert spaced("{show}._{year}", episode_context, SpaceStyle.DASH) == "Show-Name._2020"


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        (SpaceStyle.SPACE, "Show Name S01E05 Episode Name"),
        (SpaceStyle.DOT, "Show.Name.S01E05.Episode.Name"),
        (SpaceStyle.UNDERSCORE, "Show_Name_S01E05_Episode_Name"),
        (SpaceStyle.DASH, "Show-Name-S01E05-Episode-Name"),
    ],
)
def test_a_typed_space_between_tokens_takes_the_choice_as_the_values_do(
    episode_context: NamingContext, style: SpaceStyle, expected: str
) -> None:
    assert spaced("{show} {episode_code} {episode_title}", episode_context, style) == expected


def test_the_dash_between_two_spaces_is_never_joined(episode_context: NamingContext) -> None:
    template = "{show} {episode_code} - {episode_title}"
    assert spaced(template, episode_context, SpaceStyle.SPACE) == "Show Name S01E05 - Episode Name"
    assert spaced(template, episode_context, SpaceStyle.DOT) == "Show.Name.S01E05.-.Episode.Name"
    assert spaced("{show} ({year})", episode_context, SpaceStyle.DOT) == "Show.Name.(2020)"


def test_a_space_in_a_group_and_spaces_left_by_an_empty_token_are_joined_once(episode_context: NamingContext) -> None:
    track_context = replace(episode_context, track=episode_context.item.file.audio_tracks[0])
    # No HDR on this file: the group is left out, and two gaps meeting make one.
    assert spaced("{show}[ {hdr}] {codec}", track_context, SpaceStyle.DOT) == "Show.Name.Dolby.Digital.Plus"
    assert spaced("{show} {hdr} {codec}", track_context, SpaceStyle.DOT) == "Show.Name.Dolby.Digital.Plus"
    assert spaced("{show} {hdr}", track_context, SpaceStyle.DOT) == "Show.Name"


def test_a_defined_composite_joins_its_own_spaces(episode_context: NamingContext) -> None:
    context = replace(episode_context, custom=(CustomToken("both", CustomKind.COMPOSITE, "{show} by {show}"),))
    assert spaced("{both}", context, SpaceStyle.UNDERSCORE) == "Show_Name_by_Show_Name"
    context = replace(episode_context, custom=(CustomToken("both", CustomKind.COMPOSITE, "{show} {year}"),))
    assert spaced("{both}", context, SpaceStyle.UNDERSCORE) == "Show_Name_2020"


def test_the_space_choice_reaches_a_defined_pattern_and_a_composite_but_not_a_constant(
    episode_context: NamingContext,
) -> None:
    custom = (
        CustomToken("group", CustomKind.CONSTANT, "My Group"),
        CustomToken("found", CustomKind.PATTERN, r"^(.*?) \(", PatternSource.FILE_NAME),
        CustomToken("both", CustomKind.COMPOSITE, "{show} by {group}"),
    )
    context = replace(episode_context, custom=custom)
    assert spaced("{group}|{found}|{both}", context, SpaceStyle.DOT) == "My Group|Show.Name|Show.Name.by.My Group"


def test_a_replacement_is_written_as_typed(episode_context: NamingContext) -> None:
    context = replace(episode_context, value_maps={"show": {"Show Name": "Other Name"}})
    assert spaced("{show}", context, SpaceStyle.UNDERSCORE) == "Other Name"
    # A value with no row still takes the choice.
    assert spaced("{episode_title}", context, SpaceStyle.UNDERSCORE) == "Episode_Name"


def test_the_choice_of_each_template_is_its_own() -> None:
    options = NamingOptions(audio_track_space=SpaceStyle.DOT)
    assert [options.space_for(t) for t in ("title_template", "video_track_template", "audio_track_template")] == [
        SpaceStyle.SPACE,
        SpaceStyle.SPACE,
        SpaceStyle.DOT,
    ]


def test_a_saved_choice_loads_under_the_same_value() -> None:
    loaded = from_sparse(NamingOptions, {"video_track_space": "dot", "title_space": "underscore"}, "naming", [])
    assert (loaded.video_track_space, loaded.title_space) == (SpaceStyle.DOT, SpaceStyle.UNDERSCORE)


def test_old_options_load_with_spaces_kept_and_a_choice_round_trips() -> None:
    assert NamingOptions().title_space is SpaceStyle.SPACE
    loaded = from_sparse(NamingOptions, {"title_template": "{show}"}, "naming", [])
    assert loaded.audio_track_space is SpaceStyle.SPACE
    assert loaded.episode_code_format is EpisodeCodeFormat.UPPER
    chosen = NamingOptions(subtitle_track_space=SpaceStyle.DASH, episode_code_format=EpisodeCodeFormat.CROSS)
    assert to_sparse(chosen) == {"subtitle_track_space": "dash", "episode_code_format": "1x01"}
    assert from_sparse(NamingOptions, to_sparse(chosen), "naming", []) == chosen
    warnings: list = []
    assert from_sparse(NamingOptions, {"title_space": "tilde"}, "naming", warnings).title_space is SpaceStyle.SPACE
    assert warnings


# The episode code


@pytest.mark.parametrize(
    ("style", "one", "two"),
    [
        (EpisodeCodeFormat.UPPER, "S01E01", "S01E01-E02"),
        (EpisodeCodeFormat.LOWER, "s01e01", "s01e01-e02"),
        (EpisodeCodeFormat.SHORT_SEASON, "S1E01", "S1E01-E02"),
        (EpisodeCodeFormat.CROSS, "1x01", "1x01-02"),
        (EpisodeCodeFormat.SHORT_E, "1e01", "1e01-e02"),
    ],
)
def test_every_episode_code_format_for_one_and_two_episodes(style: EpisodeCodeFormat, one: str, two: str) -> None:
    assert style.value == one
    assert episode_code(style, 1, 1) == one
    assert episode_code(style, 1, 1, 2) == two


def test_a_range_of_three_and_a_last_that_is_not_after_the_first() -> None:
    assert episode_code(EpisodeCodeFormat.UPPER, 2, 18, 20) == "S02E18-E20"
    assert episode_code(EpisodeCodeFormat.UPPER, 2, 18, 18) == "S02E18"
    assert episode_code(EpisodeCodeFormat.UPPER, 10, 105) == "S10E105"
    assert episode_code(EpisodeCodeFormat.CROSS, 10, 5) == "10x05"


def test_the_token_reads_the_episode_with_its_range_in_the_chosen_format(
    episode_context: NamingContext, make_item: MakeItem
) -> None:
    assert "episode_code" in TOKENS
    assert preview("{episode_code}", episode_context).text == "S01E05"
    item = make_item()
    assert isinstance(item.identity, Episode)
    ranged = NamingContext(replace(item, identity=replace(item.identity, last_episode=6)))
    assert preview("{episode_code}", ranged).text == "S01E05-E06"
    assert preview("{episode_code}", replace(ranged, episode_code_format=EpisodeCodeFormat.LOWER)).text == "s01e05-e06"
    assert preview("{episode_code}", replace(ranged, episode_code_format=EpisodeCodeFormat.CROSS)).text == "1x05-06"


def test_a_movie_has_no_episode_code(make_item: MakeItem) -> None:
    assert preview("[{episode_code}]", NamingContext(make_item(movie=True))).text == ""


def test_the_episode_code_takes_a_replacement_like_any_token(episode_context: NamingContext) -> None:
    context = replace(episode_context, value_maps={"episode_code": {"S01E05": "S01E05 (Pilot)"}})
    assert preview("{episode_code}", context).text == "S01E05 (Pilot)"
