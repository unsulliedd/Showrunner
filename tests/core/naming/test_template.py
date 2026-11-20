from __future__ import annotations

from collections.abc import Callable

import pytest

from showrunner.core.media import MediaItem
from showrunner.core.naming import (
    SUGGESTED_TEMPLATES,
    NamingContext,
    Piece,
    PieceKind,
    Problem,
    ProblemKind,
    parse,
    pieces,
    preview,
    write,
)
from showrunner.core.track import HdrKind, Track

MakeItem = Callable[..., MediaItem]
Build = Callable[..., Track]


def text(template: str, context: NamingContext) -> str:
    return preview(template, context).text


def test_tokens_and_literal_text(episode_context: NamingContext) -> None:
    assert text("{show} - {season}x{episode} - {episode_title}", episode_context) == "Show Name - 1x5 - Episode Name"


def test_format_spec_pads_numbers(episode_context: NamingContext) -> None:
    assert text("{season:00}x{episode:00} {episode:000}", episode_context) == "01x05 005"


def test_format_spec_on_a_missing_number_stays_empty(make_item: MakeItem) -> None:
    context = NamingContext(make_item(movie=True))
    assert text("{title}[ S{season:00}]", context) == "Movie Title"


@pytest.mark.parametrize("template", ["{show:00}", "{season:x}", "{season:}", "{season:0a}"])
def test_bad_format_spec_is_reported(template: str, episode_context: NamingContext) -> None:
    result = preview(template, episode_context)
    assert [p.kind for p in result.problems] == [ProblemKind.BAD_FORMAT]


def test_token_names_ignore_case_and_spaces(episode_context: NamingContext) -> None:
    assert text("{ Show }x{SEASON:00}", episode_context) == "Show Namex01"


def test_optional_group_disappears_with_an_empty_token(make_item: MakeItem, video: Build) -> None:
    sdr = NamingContext(make_item(video()), source="Bluray")
    hdr = NamingContext(make_item(video(hdr=HdrKind.HDR10_PLUS)), source="Bluray")
    template = "{resolution}[ {hdr}] {source}"
    assert text(template, sdr) == "1080p Bluray"
    assert text(template, hdr) == "1080p HDR10+ Bluray"


def test_empty_tokens_leave_no_double_spaces_or_empty_brackets(make_item: MakeItem, video: Build) -> None:
    context = NamingContext(make_item(video(), stem="Plain Name"))  # no HDR, no source in the name
    assert text("Plain ({resolution}[ {hdr}] {source})", context) == "Plain (1080p)"
    assert text("Plain ({hdr} {source})", context) == "Plain"
    assert text("{hdr}  {resolution}", context) == "1080p"
    assert text("A[ ({hdr})] B", context) == "A B"


def test_empty_token_outside_a_group_renders_nothing(make_item: MakeItem, video: Build) -> None:
    context = NamingContext(make_item(video(), stem="Plain Name"))
    assert text("{resolution}|{source}|", context) == "1080p||"


def test_groups_nest_and_each_checks_its_own_tokens(make_item: MakeItem, video: Build) -> None:
    context = NamingContext(make_item(video(), stem="Plain Name"), source="WEB-DL")
    assert text("[{resolution}[ {hdr}][ {source}]]", context) == "1080p WEB-DL"
    assert text("[{hdr}[ {source}]]", context) == ""


def test_group_without_tokens_is_kept(episode_context: NamingContext) -> None:
    assert text("A[ - B]", episode_context) == "A - B"


def test_escapes_write_special_characters(episode_context: NamingContext) -> None:
    assert text(r"\[{season}\] \{x\} \\", episode_context) == "[1] {x} \\"


def test_unknown_token_is_reported_with_its_position(episode_context: NamingContext) -> None:
    result = preview("ab {nope} {show}", episode_context)
    assert result.problems == (Problem(ProblemKind.UNKNOWN_TOKEN, 3, 9, "nope"),)
    assert result.text == "ab Show Name"


def test_empty_braces(episode_context: NamingContext) -> None:
    assert preview("x{ }", episode_context).problems == (Problem(ProblemKind.EMPTY_TOKEN, 1, 4),)


@pytest.mark.parametrize(
    ("template", "problem"),
    [
        ("{show", Problem(ProblemKind.UNCLOSED_BRACE, 0, 1)),
        ("a {show {season}", Problem(ProblemKind.UNCLOSED_BRACE, 2, 3)),
        ("show}", Problem(ProblemKind.UNEXPECTED_CLOSE_BRACE, 4, 5)),
        ("a [ {show}", Problem(ProblemKind.UNCLOSED_GROUP, 2, 3)),
        ("{show}]", Problem(ProblemKind.UNEXPECTED_CLOSE_GROUP, 6, 7)),
        ("{show}\\", Problem(ProblemKind.TRAILING_ESCAPE, 6, 7)),
    ],
)
def test_syntax_errors_are_reported_with_positions(template: str, problem: Problem) -> None:
    assert problem in parse(template).problems


def test_syntax_errors_never_raise_at_render_time(episode_context: NamingContext) -> None:
    for broken in ["{", "}", "[", "]", "[[{", "{{}}", "\\", "{:}", "[{x}", "}{]["]:
        assert isinstance(preview(broken, episode_context).text, str)


def test_unclosed_group_still_renders_its_content(episode_context: NamingContext) -> None:
    result = preview("[{show}", episode_context)
    assert result.text == "Show Name"
    assert [p.kind for p in result.problems] == [ProblemKind.UNCLOSED_GROUP]


def test_valid_template_has_no_problems(episode_context: NamingContext) -> None:
    assert preview("{file_name} ({resolution}[ {hdr}] {source})", episode_context).problems == ()


def test_track_tokens_are_empty_without_a_track(make_item: MakeItem, video: Build, audio: Build) -> None:
    context = NamingContext(make_item(video(), audio()))
    assert text("{file_name}[ ({codec})]", context) == "Show Name (2020) - 1x05 - Episode Name"


@pytest.mark.parametrize(
    "template",
    [
        *SUGGESTED_TEMPLATES.values(),
        "{show} - S{season:00}E{episode:000}[ - {episode_title}]",
        r"a \{brace\} and \[bracket\] and \ backslash",
        "[outer [{inner}] {year}]",
        "",
    ],
)
def test_pieces_write_back_to_the_same_template(template: str) -> None:
    parsed = parse(template)
    written = write(pieces(parsed))
    assert parse(written) == parsed
    assert parse(written).problems == ()


def test_write_escapes_typed_text() -> None:
    text = "S[1]{x}\\"
    written = write([Piece(PieceKind.TEXT, text), Piece(PieceKind.TOKEN, "season", 2)])
    assert written == "S\\[1\\]\\{x\\}\\\\{season:00}"
    assert pieces(parse(written)) == [Piece(PieceKind.TEXT, text), Piece(PieceKind.TOKEN, "season", 2)]


def test_pieces_flatten_groups() -> None:
    assert pieces(parse("a[ {year}]")) == [
        Piece(PieceKind.TEXT, "a"),
        Piece(PieceKind.OPEN),
        Piece(PieceKind.TEXT, " "),
        Piece(PieceKind.TOKEN, "year"),
        Piece(PieceKind.CLOSE),
    ]
