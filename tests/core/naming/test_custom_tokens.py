from __future__ import annotations

from collections.abc import Callable

import pytest

from showrunner.core.media import MediaItem
from showrunner.core.naming import (
    CustomKind,
    CustomToken,
    NamingContext,
    NamingOptions,
    Part,
    PatternSource,
    Problem,
    ProblemKind,
    check_tokens,
    preview,
)
from showrunner.core.track import HdrKind, Track

MakeItem = Callable[..., MediaItem]
Build = Callable[..., Track]


def constant(name: str, text: str) -> CustomToken:
    return CustomToken(name, CustomKind.CONSTANT, text)


def composite(name: str, text: str) -> CustomToken:
    return CustomToken(name, CustomKind.COMPOSITE, text)


def pattern(name: str, regex: str, source: PatternSource = PatternSource.FILE_NAME) -> CustomToken:
    return CustomToken(name, CustomKind.PATTERN, regex, source)


def kinds(problems: tuple[Problem, ...]) -> list[ProblemKind]:
    return [p.kind for p in problems]


# Constants


def test_constant_token(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[constant("group", "GRP")])
    assert preview("{file_name} ({codec} {group})", context).text.endswith("(GRP)")
    assert preview("{group}", context).problems == ()


def test_constant_with_braces_is_used_as_written(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[constant("note", "{x} [y]")])
    assert preview("{note}", context).text == "{x} [y]"


def test_empty_constant_makes_a_group_disappear(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[constant("group", "")])
    assert preview("{show}[ - {group}]", context).text == "Show Name"


def test_token_names_of_defined_tokens_ignore_case_at_the_use(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[constant("group", "GRP")])
    assert preview("{Group}", context).text == "GRP"


# Composites


def test_composite_token(make_item: MakeItem, video: Build) -> None:
    item = make_item(video(hdr=HdrKind.HDR10_PLUS))
    context = NamingContext(item, source="WEB-DL", custom=[composite("quality", "{resolution}[ {hdr}] {source}")])
    assert preview("{file_name} ({quality})", context).text.endswith("(1080p HDR10+ WEB-DL)")


def test_composite_leaves_no_gaps_and_drops_groups_when_empty(make_item: MakeItem, video: Build) -> None:
    context = NamingContext(
        make_item(video(), stem="Plain Name"), custom=[composite("quality", "{resolution}[ {hdr}] {source}")]
    )
    assert preview("{quality}", context).text == "1080p"
    assert preview(r"Plain[ \[{quality}\]]", context).text == "Plain [1080p]"


def test_composite_of_empty_tokens_is_empty(make_item: MakeItem) -> None:
    context = NamingContext(make_item(stem="Plain Name"), custom=[composite("quality", "{hdr} {source}")])
    assert preview("Plain[ ({quality})]", context).text == "Plain"


def test_composites_nest(episode_context: NamingContext) -> None:
    custom = [composite("code", "{season:00}x{episode:00}"), composite("label", "{show} - {code}")]
    context = NamingContext(episode_context.item, custom=custom)
    assert preview("{label}", context).text == "Show Name - 01x05"


def test_cycle_is_reported_at_the_use_and_renders_empty(episode_context: NamingContext) -> None:
    custom = [composite("loop", "a{loop}")]
    result = preview("x {loop}", NamingContext(episode_context.item, custom=custom))
    assert result.problems == (Problem(ProblemKind.CYCLE, 2, 8, "loop > loop"),)
    assert result.text == "x a"


def test_longer_cycle_names_the_chain(episode_context: NamingContext) -> None:
    custom = [composite("a", "{b}"), composite("b", "{c}"), composite("c", "{a}")]
    result = preview("{a}", NamingContext(episode_context.item, custom=custom))
    assert result.problems == (Problem(ProblemKind.CYCLE, 0, 3, "a > b > c > a"),)


def test_unknown_token_inside_a_composite_is_reported_at_the_use(episode_context: NamingContext) -> None:
    custom = [composite("label", "{show} {nope}")]
    result = preview("[{label}]", NamingContext(episode_context.item, custom=custom))
    assert result.problems == (Problem(ProblemKind.UNKNOWN_TOKEN, 1, 8, "nope"),)
    assert result.text == "Show Name"


def test_syntax_error_inside_a_composite_is_reported_at_the_use(episode_context: NamingContext) -> None:
    result = preview("{label}", NamingContext(episode_context.item, custom=[composite("label", "{show")]))
    assert kinds(result.problems) == [ProblemKind.UNCLOSED_BRACE]


def test_format_spec_on_a_defined_token_is_reported(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[constant("group", "GRP")])
    assert preview("{group:00}", context).problems == (Problem(ProblemKind.BAD_FORMAT, 0, 10, "00"),)


# Patterns


def test_pattern_reads_the_first_group_from_the_file_name(make_item: MakeItem) -> None:
    item = make_item(stem="Show.Name.S01E05.1080p.WEB-DL-GRP")
    context = NamingContext(item, custom=[pattern("release_group", r"-([^-]+)$")])
    assert preview("{release_group}", context).text == "GRP"


def test_pattern_without_a_match_is_empty(make_item: MakeItem) -> None:
    context = NamingContext(make_item(stem="No Group"), custom=[pattern("group", r"-([^-]+)$")])
    assert preview("Name[ ({group})]", context).text == "Name"
    assert preview("{group}", context).problems == ()


def test_pattern_reads_from_a_parent_folder(tmp_path_factory: pytest.TempPathFactory, make_item: MakeItem) -> None:
    item = make_item()
    from dataclasses import replace
    from pathlib import Path

    path = Path("Library/Show Name [2020] [GRP]/Season 1") / item.file.path.name
    item = replace(item, file=replace(item.file, path=path))
    custom = [
        pattern("one", r"(Season \d+)", PatternSource.FOLDER_1),
        pattern("two", r"\[([A-Za-z]+)\]$", PatternSource.FOLDER_2),
        pattern("three", r"(Library)", PatternSource.FOLDER_3),
        pattern("four", r"(.+)", PatternSource.FOLDER_1),
    ]
    context = NamingContext(item, custom=custom)
    assert preview("{one}|{two}|{three}", context).text == "Season 1|GRP|Library"
    shallow = replace(item, file=replace(item.file, path=Path("file.mkv")))
    assert preview("{one}{two}", NamingContext(shallow, custom=custom)).problems == ()
    assert preview("[{one}]", NamingContext(shallow, custom=custom)).text == ""


def test_invalid_pattern_is_reported_not_raised(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[pattern("bad", "([")])
    result = preview("a {bad}", context)
    assert kinds(result.problems) == [ProblemKind.BAD_PATTERN]
    assert (result.problems[0].start, result.problems[0].end) == (2, 7)
    assert result.text == "a"


def test_pattern_without_a_group_is_reported(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[pattern("flat", "Show")])
    assert kinds(preview("{flat}", context).problems) == [ProblemKind.PATTERN_WITHOUT_GROUP]


# Value maps


def test_value_map_rewrites_a_built_in_token(make_item: MakeItem, video: Build, audio: Build) -> None:
    track = audio(channels=2)
    item = make_item(video(), track)
    maps = {"channels": {"2.0": "Stereo"}, "language": {"English": "İngilizce"}}
    context = NamingContext(item, track, value_maps=maps)
    assert preview("{channels} {language}", context).text == "Stereo İngilizce"
    other = NamingContext(item, audio(channels=6), value_maps=maps)
    assert preview("{channels}", other).text == "5.1"


def test_value_map_on_the_default_display_names(make_item: MakeItem, audio: Build) -> None:
    track = audio("A_DTS")
    context = NamingContext(make_item(track), track, value_maps={"codec": {"DTS": "DTS-HD Master Audio"}})
    assert preview("{codec}", context).text == "DTS-HD Master Audio"


def test_value_map_applies_to_numbers_and_skips_padding(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, value_maps={"season": {"1": "One"}})
    assert preview("{season:00} {episode:00}", context).text == "One 05"


def test_value_map_to_empty_hides_the_token(make_item: MakeItem, audio: Build) -> None:
    track = audio(channels=2)
    context = NamingContext(make_item(track), track, value_maps={"channels": {"2.0": ""}})
    assert preview("Name[ {channels}]", context).text == "Name"


def test_value_map_on_defined_tokens(episode_context: NamingContext) -> None:
    custom = [constant("group", "GRP"), composite("label", "{group}!")]
    maps = {"group": {"GRP": "Tao"}, "label": {"Tao!": "Labelled"}}
    context = NamingContext(episode_context.item, custom=custom, value_maps=maps)
    assert preview("{group} {label}", context).text == "Tao Labelled"


def test_value_map_does_not_touch_unlisted_or_empty_values(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, value_maps={"hdr": {"": "SDR"}})
    assert preview("[{hdr}]", context).text == ""


# Shadowing


def test_shadowing_a_built_in_is_reported_at_the_use_and_the_built_in_wins(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[constant("show", "Other")])
    result = preview("{show}", context)
    assert result.text == "Show Name"
    assert result.problems == (Problem(ProblemKind.SHADOWS_BUILTIN, 0, 6, "show"),)


def test_first_definition_of_a_name_wins(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[constant("g", "one"), constant("g", "two")])
    assert preview("{g}", context).text == "one"


# Literal text and escapes


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (r"\{{show}\}", "{Show Name}"),
        (r"\[{show}\]", "[Show Name]"),
        (r"\[\]\{\}", "[]{}"),
        (r"{show} \\ x", "Show Name \\ x"),
        (r"[\[ {show}\] ]", "[ Show Name]"),
        (r"{show} (GRP)", "Show Name (GRP)"),
    ],
)
def test_literal_brackets_and_braces(template: str, expected: str, episode_context: NamingContext) -> None:
    result = preview(template, episode_context)
    assert result.text == expected
    assert result.problems == ()


def test_escapes_work_inside_a_composite(episode_context: NamingContext) -> None:
    context = NamingContext(episode_context.item, custom=[composite("tagged", r"\[{show}\]")])
    assert preview("{tagged}", context).text == "[Show Name]"


# Checking the definitions


def test_check_accepts_good_definitions() -> None:
    custom = [
        constant("group", "GRP"),
        composite("quality", "{resolution}[ {hdr}] {source}"),
        composite("label", "{quality} {group}"),
        pattern("release_group", r"-([^-]+)$"),
    ]
    assert check_tokens(custom, {"channels": {"2.0": "Stereo"}, "group": {}, "quality": {}}) == []


def test_check_reports_a_cycle_with_its_position() -> None:
    found = check_tokens([composite("a", "x {b}"), composite("b", "{a}")])
    assert [(f.name, f.part, f.problem.kind, f.problem.start, f.problem.end) for f in found] == [
        ("a", Part.TEXT, ProblemKind.CYCLE, 2, 5),
        ("b", Part.TEXT, ProblemKind.CYCLE, 0, 3),
    ]


def test_check_reports_a_self_reference() -> None:
    (found,) = check_tokens([composite("loop", "{loop}")])
    assert found.problem == Problem(ProblemKind.CYCLE, 0, 6, "loop > loop")


def test_check_reports_unknown_tokens_and_syntax_errors_in_a_composite() -> None:
    found = check_tokens([composite("x", "{show} {nope} {season:q}")])
    assert [(f.problem.kind, f.problem.start) for f in found] == [
        (ProblemKind.UNKNOWN_TOKEN, 7),
        (ProblemKind.BAD_FORMAT, 14),
    ]


def test_check_reports_invalid_patterns() -> None:
    found = check_tokens([pattern("bad", "a(b"), pattern("flat", "abc")])
    assert [(f.name, f.part, f.problem.kind) for f in found] == [
        ("bad", Part.TEXT, ProblemKind.BAD_PATTERN),
        ("flat", Part.TEXT, ProblemKind.PATTERN_WITHOUT_GROUP),
    ]
    assert found[0].problem.detail


def test_check_reports_shadowing_invalid_and_duplicate_names() -> None:
    found = check_tokens([constant("hdr", "x"), constant("Bad Name", "x"), constant("g", "1"), constant("g", "2")])
    assert [(f.name, f.part, f.problem.kind) for f in found] == [
        ("hdr", Part.NAME, ProblemKind.SHADOWS_BUILTIN),
        ("Bad Name", Part.NAME, ProblemKind.INVALID_NAME),
        ("g", Part.NAME, ProblemKind.DUPLICATE_NAME),
    ]


def test_check_reports_value_maps_of_unknown_tokens() -> None:
    found = check_tokens([constant("group", "x")], {"group": {}, "channels": {}, "gone": {"a": "b"}})
    assert [(f.name, f.problem.kind) for f in found] == [("gone", ProblemKind.UNKNOWN_TOKEN)]


def test_default_options_have_no_custom_tokens() -> None:
    options = NamingOptions()
    assert (options.custom_tokens, options.value_maps) == ([], {})
