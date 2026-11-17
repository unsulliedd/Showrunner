"""The Names builders: rail edits that write a template back as text, the rail's parts, the underlined result and
what the place and the Tokens panel show."""

from __future__ import annotations

from dataclasses import replace

import pytest

from showrunner.app.batches.batch import Media
from showrunner.app.jobs.blocked import StageBlock
from showrunner.app.library.library import Library
from showrunner.core.media import MediaItem
from showrunner.core.naming import (
    SUGGESTED_TEMPLATES,
    CustomKind,
    CustomToken,
    NamingOptions,
    Problem,
    ProblemKind,
    parse,
    preview,
)
from showrunner.stages.tracks import TracksOptions
from showrunner.ui.quick import names
from showrunner.ui.quick.names import NamesInput

EPISODE = "{show} - S{season:00}E{episode:00}[ - {episode_title}]"


def season(library: Library) -> list[MediaItem]:
    return [i for i in library.items if "S01E" in i.file.path.name and "Show.Name" in i.file.path.name]


def given(
    items: list[MediaItem], naming: NamingOptions, template: str = "title_template", **more: object
) -> NamesInput:
    values: dict[object, object] = {
        "items": items,
        "focus": items[2],
        "media": Media.EPISODES,
        "naming": naming,
        "tracks": TracksOptions(),
        "template": template,
        "files": (),
        "block": None,
        "batch_title": "Season 1",
    }
    values.update(more)
    return NamesInput(**values)  # type: ignore[arg-type]


# Rail edits


def test_rail_edits_write_templates_the_engine_reads() -> None:
    assert names.insert_token("S", 1, "season") == "S{season}"
    assert names.move_token("{show} - {year}", 2, 0) == "{year}{show} - "
    assert names.move_token("{show} - {year}", 0, 3) == " - {year}{show}"
    assert names.remove_piece("{show} - {year}", 1) == "{show}{year}"
    assert names.set_text("{show} - {year}", 1, " [x] ") == r"{show} \[x\] {year}"
    assert names.set_text("{show} - {year}", 1, "") == "{show}{year}"
    assert names.add_text("{show}{year}", 1, " (") == "{show} ({year}"
    for result in ("S{season}", r"{show} \[x\] {year}", "{show} ({year}"):
        assert parse(result).problems == ()


def test_a_token_made_optional_takes_the_text_before_it() -> None:
    wrapped = names.toggle_optional("{show} - {episode_title}", 2)
    assert wrapped == "{show}[ - {episode_title}]"
    # Toggled again inside its group, the brackets go and the text stays.
    assert names.toggle_optional(wrapped, 3) == "{show} - {episode_title}"
    assert names.toggle_optional("{show}{year}", 1) == "{show}[{year}]"


def test_number_padding_steps_and_text_tokens_have_none() -> None:
    assert names.cycle_padding("{season}", 0) == "{season:00}"
    assert names.cycle_padding("{season:00}", 0) == "{season:000}"
    assert names.cycle_padding("{season:000}", 0) == "{season}"
    assert names.cycle_padding("{show}", 0) == "{show}"


def test_a_template_with_syntax_problems_is_never_rewritten() -> None:
    broken = "{show - {year}"
    assert names.insert_token(broken, 0, "season") == broken
    assert names.remove_piece(broken, 0) == broken
    assert names.rail(broken, None, ()) == []


def test_edits_out_of_range_change_nothing() -> None:
    assert names.remove_piece("{show}", 5) == "{show}"
    assert names.move_token("{show} x", 1, 0) == "{show} x"  # text is not moved
    assert names.set_text("{show}", 0, "x") == "{show}"


def test_a_rename_carries_every_use_of_the_token() -> None:
    naming = NamingOptions(
        title_template="{group} - {show}",
        audio_track_template="[{group}]",
        custom_tokens=[CustomToken("group", text="GRP"), CustomToken("tag", CustomKind.COMPOSITE, "{group}!")],
        value_maps={"group": {"GRP": "Group"}},
    )
    renamed = names.rename_token(naming, "group", "team")
    assert (renamed.title_template, renamed.audio_track_template) == ("{team} - {show}", "[{team}]")
    assert renamed.custom_tokens[1].text == "{team}!"
    assert renamed.value_maps == {"team": {"GRP": "Group"}}
    # A name a template cannot hold is not carried: the uses stay and show as unknown.
    assert names.rename_token(naming, "group", "Bad Name") == naming


def test_a_new_token_takes_a_free_name() -> None:
    assert names.new_token_name([]) == "token_1"
    assert names.new_token_name([CustomToken("token_1"), CustomToken("token_3")]) == "token_2"


# The rail's parts


def test_the_rail_shows_chips_text_groups_and_slots(library: Library) -> None:
    items = season(library)
    (focused,) = (
        e for e in names.named(items, "title_template", NamingOptions(), TracksOptions()) if e.item is items[2]
    )
    parts = names.rail(EPISODE + "{nope}", focused.context, ())
    kinds = [p["kind"] for p in parts]
    assert kinds == ["slot", "token", "text", "token", "text", "token", "slot", "group", "slot", "token", "slot"]
    season_chip, group = parts[3], parts[7]
    assert (season_chip["label"], season_chip["format"], season_chip["at"]) == ("Season", "01", 2)
    assert (group["at"], group["end"]) == (5, 8)
    assert [p["kind"] for p in group["parts"]] == ["text", "token", "slot"]
    assert group["parts"][-1]["at"] == 8  # typed at the group's end, before its bracket
    assert parts[-2]["known"] is False
    assert parts[-1]["at"] == 10


# The result


@pytest.mark.parametrize("template", [*SUGGESTED_TEMPLATES, "title_template"])
def test_the_underlined_parts_join_to_the_engines_result(library: Library, template: str) -> None:
    items = season(library)
    text = SUGGESTED_TEMPLATES[template] if template != "title_template" else EPISODE
    for entry in names.named(items[:2], template, NamingOptions(), TracksOptions()):
        parts = names.segments(text, entry.context)
        assert "".join(str(p["text"]) for p in parts) == preview(text, entry.context).text
        assert any(p["token"] for p in parts)


def test_the_result_underlines_each_tokens_value(library: Library) -> None:
    items = season(library)
    (entry,) = (e for e in names.named(items, "title_template", NamingOptions(), TracksOptions()) if e.item is items[2])
    assert names.segments(EPISODE, entry.context) == [
        {"text": "Show Name", "token": True},
        {"text": " - S", "token": False},
        {"text": "01", "token": True},
        {"text": "E", "token": False},
        {"text": "03", "token": True},
        {"text": " - ", "token": False},
        {"text": "Episode Three", "token": True},
    ]


def test_a_file_that_loses_a_group_is_explained(library: Library) -> None:
    first = season(library)[0]
    untitled = replace(first, identity=replace(first.identity, episode_title=None))
    (entry,) = names.named([untitled], "title_template", NamingOptions(), TracksOptions())
    assert names.loss_text(EPISODE, entry.context) == "No Episode title in this file: the part around it is left out"
    assert names.loss_text("{show} {year}", entry.context) == ""
    assert names.loss_text("{movie}", entry.context) == "No Movie in this file: that part stays empty"


# The place


def test_cards_follow_the_engines_templates_and_the_batch_kind(library: Library) -> None:
    items = season(library)
    shown = names.place(given(items, NamingOptions(title_template=EPISODE)))
    cards = shown["cards"]
    assert [c["label"] for c in cards] == [
        "File title",
        "Video track names",
        "Audio track names",
        "Subtitle track names",
    ]
    assert cards[0]["sample"] == "Show Name - S01E03 - Episode Three"
    assert (cards[1]["empty"], cards[1]["stays"], cards[1]["count_text"]) == (
        True,
        "Names stay as they are",
        "",
    )
    movies = names.place(given(items, NamingOptions(), media=Media.MOVIES))
    assert movies["cards"][0]["label"] == "File title"


def test_only_the_file_title_says_it_is_not_the_file_name(library: Library) -> None:
    items = season(library)
    title = names.place(given(items, NamingOptions()))
    assert "not the file's name" in str(title["note"])
    assert names.place(given(items, NamingOptions(), template="audio_track_template"))["note"] == ""


def test_the_place_shows_the_batch_before_and_after(library: Library) -> None:
    items = season(library)
    shown = names.place(given(items, NamingOptions(title_template=EPISODE)))
    assert shown["result"]["label"] == "Episode Three becomes"
    first = shown["rows"][0]
    assert (first["number"], first["now"], first["now_empty"]) == ("01", "(no title)", True)
    assert (first["after"], first["changed"]) == ("Show Name - S01E01 - Episode One", True)
    assert [r["focused"] for r in shown["rows"]].index(True) == 2
    assert shown["rows_title"] == "Preview on Season 1"
    # An empty template shows no rows and offers the suggestion's result.
    empty = names.place(given(items, NamingOptions()))
    assert (empty["empty"], empty["rows"], empty["suggestion"]) == (True, [], "Show.Name.S01E03")


def test_track_templates_name_each_kept_track(library: Library) -> None:
    items = season(library)
    naming = NamingOptions(audio_track_template="{language} {channels}")
    shown = names.place(given(items, naming, "audio_track_template"))
    assert shown["result"]["label"] == "English in Episode Three becomes"
    assert [r["after"] for r in shown["rows"][:3]] == ["English 5.1", "Turkish 5.1", "English 2.0"]


def test_problems_are_worded_in_place(library: Library) -> None:
    items = season(library)
    shown = names.place(given(items, NamingOptions(title_template="{shwo}")))
    assert shown["problems"] == ["Unknown token {shwo}."]
    assert shown["cards"][0]["problem"] is True
    block = StageBlock(
        "metadata",
        {"audio_track_template": (Problem(ProblemKind.UNKNOWN_TOKEN, 0, 4, "x"),)},
        language="xx-??",
    )
    lines = names.place(given(items, NamingOptions(), block=block))["blocked"]
    assert lines == [
        "Audio track names: Unknown token {x}.",
        "The language for untagged tracks is not a language code: xx-??",
    ]
    broken = names.place(given(items, NamingOptions(title_template="{show")))
    assert (broken["editable"], broken["rail"]) == (False, [])


# The Tokens panel


def test_tokens_are_grouped_with_their_values(library: Library) -> None:
    items = season(library)
    panel = names.tokens(given(items, NamingOptions(custom_tokens=[CustomToken("group", text="GRP")])), "", -1)
    groups = {g["key"]: g for g in panel["groups"]}
    assert list(groups) == ["item", "video", "track", "custom"]
    show = next(t for t in groups["item"]["tokens"] if t["name"] == "show")
    assert (show["label"], show["value"]) == ("Show", "Show Name")
    assert groups["custom"]["tokens"] == [{"name": "group", "label": "group", "value": "GRP", "index": 0}]
    assert panel["editor"] == {}
    found = names.tokens(given(items, NamingOptions()), "episode t", -1)["groups"]
    assert [t["name"] for g in found for t in g["tokens"]] == ["episode_title"]


def test_the_editor_shows_a_patterns_result_on_the_batch(library: Library) -> None:
    items = season(library)
    token = CustomToken("code", CustomKind.PATTERN, r"(S\d+E\d+)")
    editor = names.tokens(given(items, NamingOptions(custom_tokens=[token])), "", 0)["editor"]
    assert (editor["kind"], editor["value"], editor["found"]) == ("pattern", "S01E03", "10 of 10")
    assert editor["value_label"] == "On Episode Three"
    bad = CustomToken("code", CustomKind.PATTERN, "S01")
    editor = names.tokens(given(items, NamingOptions(custom_tokens=[bad])), "", 0)["editor"]
    assert editor["text_problems"] == ["A pattern needs a group in parentheses: its text is the value."]
    assert editor["found"] == "0 of 10"


def test_a_group_left_without_a_token_loses_its_brackets() -> None:
    assert names.remove_piece("{show}[ - {episode_title}]", 3) == "{show} - "
    assert names.move_token("{show}[ - {episode_title}]", 3, 0) == "{episode_title}{show} - "
    assert names.remove_piece("{show}[ {year}[ {hdr}]]", 3) == "{show} [ {hdr}]"
    assert names.remove_piece("{show}[ {year} {hdr}]", 3) == "{show}[  {hdr}]"


def test_a_part_left_out_is_noted_only_where_a_file_differs(library: Library) -> None:
    items = season(library)
    untitled = replace(items[1], identity=replace(items[1].identity, episode_title=None))
    batch = [items[0], untitled, *items[2:]]
    rows = names.place(given(batch, NamingOptions(title_template=EPISODE)))["rows"]
    assert [r["note"] for r in rows if r["note"]] == ["No Episode title in this file: the part around it is left out"]
    # Most tracks have no flags, so the flags group left out is no news on any row.
    audio = names.place(
        given(
            items,
            NamingOptions(audio_track_template=SUGGESTED_TEMPLATES["audio_track_template"]),
            "audio_track_template",
        )
    )["rows"]
    assert all(r["note"] == "" for r in audio)
