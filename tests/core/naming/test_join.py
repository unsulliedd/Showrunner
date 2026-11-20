"""Pieces join themselves: tokens, separators and typed text in a row, and where the join character goes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from showrunner.core.media import MediaItem
from showrunner.core.naming import (
    SEPARATORS,
    SUGGESTED_TEMPLATES,
    CustomKind,
    CustomToken,
    NamingContext,
    PieceKind,
    SpaceStyle,
    parse,
    pieces,
    preview,
    write,
)
from showrunner.core.track import HdrKind, Track

MakeItem = Callable[..., MediaItem]
Build = Callable[..., Track]


def made(template: str, context: NamingContext, style: SpaceStyle = SpaceStyle.SPACE) -> str:
    return preview(template, replace(context, space=style)).text


@pytest.mark.parametrize(
    ("template", "space", "dot"),
    [
        ("{show}{episode_code}", "Show Name S01E05", "Show.Name.S01E05"),
        ("S{season:00}E{episode:00}", "S01E05", "S01E05"),
        ("{show}-{episode_code}", "Show Name - S01E05", "Show.Name.-.S01E05"),
        ("{show}.{episode_code}", "Show Name.S01E05", "Show.Name.S01E05"),
        ("{show}_{episode_code}", "Show Name_S01E05", "Show.Name_S01E05"),
        ("{show}({year})", "Show Name (2020)", "Show.Name.(2020)"),
        (r"{show}\[{year}\]", "Show Name [2020]", "Show.Name.[2020]"),
        (r"{show}\{{year}\}", "Show Name {2020}", "Show.Name.{2020}"),
        ("{show}({year}){episode_code}", "Show Name (2020) S01E05", "Show.Name.(2020).S01E05"),
        ("{show}({year})-{episode_code}", "Show Name (2020) - S01E05", "Show.Name.(2020).-.S01E05"),
    ],
)
def test_neighbouring_pieces_take_the_join_character_by_their_sides(
    episode_context: NamingContext, template: str, space: str, dot: str
) -> None:
    assert made(template, episode_context) == space
    assert made(template, episode_context, SpaceStyle.DOT) == dot


def test_every_separator_knows_its_sides() -> None:
    assert SEPARATORS == {
        "-": (True, True),
        ".": (False, False),
        "_": (False, False),
        "(": (True, False),
        "[": (True, False),
        "{": (True, False),
        ")": (False, True),
        "]": (False, True),
        "}": (False, True),
    }


@pytest.mark.parametrize(
    "template",
    [
        "{show} - {episode_code} - {episode_title}",
        "{show} ({year})",
        "{show} ({year}) - {episode_code}",
        "S{season:00}E{episode:00}",
        "{season:00}x{episode:00}",
        "{show} {episode_code}[ - {episode_title}]",
    ],
)
def test_templates_with_typed_spaces_read_the_same_as_before_under_space(
    episode_context: NamingContext, template: str
) -> None:
    expected = {
        "{show} - {episode_code} - {episode_title}": "Show Name - S01E05 - Episode Name",
        "{show} ({year})": "Show Name (2020)",
        "{show} ({year}) - {episode_code}": "Show Name (2020) - S01E05",
        "S{season:00}E{episode:00}": "S01E05",
        "{season:00}x{episode:00}": "01x05",
        "{show} {episode_code}[ - {episode_title}]": "Show Name S01E05 - Episode Name",
    }[template]
    assert made(template, episode_context) == expected


def test_the_suggested_templates_read_the_same_as_before_with_and_without_the_optional_token(
    make_item: MakeItem, video: Build, audio: Build, base: str
) -> None:
    sdr, hdr = make_item(video(), audio()), make_item(video(hdr=HdrKind.HDR10_PLUS), audio())
    for item, hdr_part in ((sdr, ""), (hdr, " HDR10+")):
        context = NamingContext(item, item.file.video_tracks[0], source="WEB-DL")
        assert made(SUGGESTED_TEMPLATES["title_template"], context) == base
        assert made(SUGGESTED_TEMPLATES["video_track_template"], context) == f"{base} (1080p{hdr_part} WEB-DL)"
        context = NamingContext(item, item.file.audio_tracks[0], source="WEB-DL")
        assert made(SUGGESTED_TEMPLATES["audio_track_template"], context) == f"{base} (Dolby Digital Plus 5.1)"


def test_a_bare_separator_or_two_pieces_side_by_side_now_join_under_space(episode_context: NamingContext) -> None:
    # A separator chip is stored as its character, so a bare dash or bracket joins; tokens side by side join too.
    assert made("{show}-{episode_code}", episode_context) == "Show Name - S01E05"
    assert made("{show}({year})", episode_context) == "Show Name (2020)"
    assert made("{show}{year}", episode_context) == "Show Name 2020"


def test_a_run_of_separators_is_one_separator_per_character(episode_context: NamingContext) -> None:
    parts = pieces(parse("{show}({year})-{episode_code}"))
    assert [(p.kind, p.text) for p in parts] == [
        (PieceKind.TOKEN, "show"),
        (PieceKind.CHIP, "("),
        (PieceKind.TOKEN, "year"),
        (PieceKind.CHIP, ")"),
        (PieceKind.CHIP, "-"),
        (PieceKind.TOKEN, "episode_code"),
    ]
    # A run with any other character, a space included, is typed text.
    assert [(p.kind, p.text) for p in pieces(parse("{show} - {year}"))][1] == (PieceKind.TEXT, " - ")
    assert [p.kind for p in pieces(parse("{show}x-{year}"))] == [PieceKind.TOKEN, PieceKind.TEXT, PieceKind.TOKEN]


@pytest.mark.parametrize("template", [r"\[\]\{\}", "{show}-({year})_{season}.", r"{show}\[{year}\]\{x\}"])
def test_separators_round_trip_through_pieces_and_escape_the_brackets_and_braces(template: str) -> None:
    assert write(pieces(parse(template))) == template
    assert not parse(template).problems


def test_brackets_and_braces_as_chips_are_not_a_group_or_a_token(episode_context: NamingContext) -> None:
    parts = pieces(parse(r"\[\]\{\}"))
    assert [(p.kind, p.text) for p in parts] == [(PieceKind.CHIP, c) for c in "[]{}"]
    assert made(r"{show}\[{year}\]", episode_context) == "Show Name [2020]"


def test_an_empty_token_makes_one_join_and_empty_brackets_go(episode_context: NamingContext) -> None:
    no_hdr = episode_context  # no track: `{hdr}` is empty
    assert made("{show}{hdr}{year}", no_hdr) == "Show Name 2020"
    assert made("{show}({hdr}){year}", no_hdr) == "Show Name 2020"
    assert made(r"{show}\[{hdr}\]{year}", no_hdr) == "Show Name 2020"
    assert made(r"{show}\{{hdr}\}{year}", no_hdr) == "Show Name 2020"
    assert made("{show} ({hdr}) {year}", no_hdr) == "Show Name 2020"
    # Brackets typed on purpose, with nothing between them, stay.
    assert made(r"{show}\[\]", no_hdr) == "Show Name []"


def test_a_left_out_group_lets_its_neighbours_meet_once(episode_context: NamingContext) -> None:
    assert made("{show}[{hdr}]{year}", episode_context) == "Show Name 2020"
    assert made("{show}[{season}]{year}", episode_context) == "Show Name 1 2020"
    assert made("{show}[({hdr})]{year}", episode_context) == "Show Name 2020"


def test_a_defined_token_joins_its_own_pieces_and_sits_among_the_others(episode_context: NamingContext) -> None:
    both = CustomToken("both", CustomKind.COMPOSITE, "{show}-{year}")
    context = replace(episode_context, custom=(both,))
    assert made("{both}{season}", context) == "Show Name - 2020 1"
    assert made("{both}{season}", context, SpaceStyle.DOT) == "Show.Name.-.2020.1"
    group = CustomToken("group", CustomKind.CONSTANT, "My Group")
    assert made("{show}-{group}", replace(episode_context, custom=(group,))) == "Show Name - My Group"


def test_file_title_stays_verbatim_and_joins_to_its_neighbours(make_item: MakeItem, subtitle: Build) -> None:
    track = subtitle()
    item = make_item(track)
    context = NamingContext(item, track, space=SpaceStyle.DOT, file_title="Show Name - 1x05")
    assert preview("{file_title}{language}", context).text == "Show Name - 1x05.Turkish"
    assert preview("{file_title}({language})", context).text == "Show Name - 1x05.(Turkish)"
