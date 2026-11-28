"""The Subtitles place: its rows show the place's subtitle settings with where each value comes from, the row menu
follows the parent again or makes "as it is" the place's own value, and the file list names each file's work. Work no
engine can do is left out and said so, in the tab and in Review."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QMetaObject
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.core.track import TrackKind
from showrunner.ui.quick.window import WindowController

from .conftest import neutral_library
from .test_choices import open_season, settle


def row(controller: WindowController, key: str) -> dict[str, Any]:
    return next(r for r in controller.subtitles["rows"] if r["key"] == key)


def add_language(controller: WindowController, tag: str) -> None:
    controller.pick_wanted_language()
    controller.language_picker.set_typed(tag)
    controller.language_picker.apply()


def test_a_show_s_settings_reach_its_season_marked_and_the_season_overrides_them(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    controller.set_subtitle_choice("sync", "alass")
    add_language(controller, "de")
    settle(controller, qtbot)
    assert controller.subtitles["title"] == "Subtitles in this show"
    assert controller.subtitles["follow"] == ""  # the show has nothing above it to follow
    controller.select(season)
    settle(controller, qtbot)
    assert controller.subtitles["title"] == "Subtitles in this season"
    assert (row(controller, "sync")["value"], row(controller, "sync")["received"]) == ("alass", True)
    assert controller.field_marks["subtitles.sync"] == {"from": "From the show", "over": ""}
    (german,) = row(controller, "wanted")["items"]
    assert (german["label"], german["off"], german["mark"]["from"]) == ("DEU", False, "From the show")
    # Every episode gets a German subtitle, translated from its reference.
    assert controller.workspace_tabs[2]["key"] == "subtitles"
    assert controller.workspace_tabs[2]["count"] > 0
    plan = controller.subtitles["files"][0]["plan"]
    assert [(p["code"], p["steps"]) for p in plan] == [("DEU", "translate")]

    # The season says no to German for itself, and picks its own engine.
    controller.toggle_subtitle_item("wanted", "de")
    controller.set_subtitle_choice("sync", "ffsubsync")
    settle(controller, qtbot)
    (german,) = row(controller, "wanted")["items"]
    assert (german["off"], german["mark"]["over"]) == (True, "Overrides the show")
    assert controller.field_marks["subtitles.sync"] == {"from": "", "over": "Overrides the show"}
    # No work is planned: the Turkish file beside the video is not added, and the row says so.
    assert [(p["code"], p["steps"], p["cannot"]) for p in controller.subtitles["files"][0]["plan"]] == [
        ("TUR", "", "Beside the video, not added · Add it on Tracks")
    ]
    assert controller.subtitles["follow"] == "Follow the show again"

    # The row menu: follow the show again, or "as it is" as the season's own value.
    controller.follow_subtitles("sync")
    assert (row(controller, "sync")["value"], row(controller, "sync")["own"]) == ("alass", False)
    controller.subtitles_as_it_is("sync")
    assert (row(controller, "sync")["value"], row(controller, "sync")["own"]) == ("", True)
    controller.toggle_subtitle_item("wanted", "de")
    assert row(controller, "wanted")["items"][0]["off"] is False
    controller.subtitles_as_it_is("wanted")
    assert row(controller, "wanted")["items"][0]["off"] is True
    # Discard changes takes every own value away.
    controller.discard_changes()
    settle(controller, qtbot)
    assert row(controller, "sync")["value"] == "alass"
    assert row(controller, "wanted")["items"][0]["off"] is False


def test_review_shows_the_subtitles_group_with_counts_that_add_up(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    add_language(controller, "de")
    settle(controller, qtbot)
    shown = controller.review
    group = next(g for g in shown["groups"] if g["key"] == "subtitles")
    # Ten translations, and the ten new files only they ask for.
    assert [(line["label"], line["count"]) for line in group["lines"]] == [
        ("Finished subtitles", 10),
        ("New files only subtitles ask for", 10),
    ]
    assert group["problems"] == []
    assert "Subtitles" not in shown["stays"]
    assert shown["count"] == sum(line["count"] for g in shown["groups"] for line in g["lines"])
    first = shown["rows"][0]
    assert [m["key"] for m in first["marks"]] == ["tracks", "names", "subtitles"]
    assert next(m for m in first["marks"] if m["key"] == "subtitles")["on"]


def test_work_no_engine_can_do_is_left_out_and_said_so(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    tracks_before = controller.workspace_tabs[1]["count"]
    states_before = [r["state"] for r in controller.review["rows"]]
    add_language(controller, "de")
    controller.set_subtitle_choice("sync", "alass")
    settle(controller, qtbot)
    # No AI server answers here, so nothing is planned for subtitles and the track choices plan as before.
    assert controller.workspace_tabs[2]["count"] == 0
    assert controller.workspace_tabs[1]["count"] == tracks_before
    assert row(controller, "wanted")["note"] == ""
    assert row(controller, "model")["note"] == "Ollama is not running"
    assert row(controller, "sync")["note"] == ""  # no paired file is added, so nothing asks for a sync
    plan = controller.subtitles["files"][0]["plan"]
    assert [(p["code"], p["cannot"]) for p in plan] == [("DEU", "Ollama is not running")]
    shown = controller.review
    group = next(g for g in shown["groups"] if g["key"] == "subtitles")
    assert group["lines"] == []
    assert group["problems"] == [
        "Ollama is not running, so 10 subtitles are left out. The rest of each file goes on without them."
    ]
    # Left out is not a look: the files go on with their other changes.
    assert [r["state"] for r in shown["rows"]] == states_before


def test_a_file_that_cannot_get_its_subtitle_needs_a_look_and_says_why(
    controller: WindowController, qtbot: QtBot
) -> None:
    sample = neutral_library()
    first = sample.items[0]
    bare = replace(first.file, tracks=tuple(t for t in first.file.tracks if t.kind is not TrackKind.SUBTITLE))
    library = replace(sample, items=(replace(first, file=bare), *sample.items[1:]))
    open_season(controller, library, qtbot, episode=0)
    add_language(controller, "de")
    settle(controller, qtbot)
    plan = controller.subtitles["files"][0]["plan"]
    assert [(p["code"], p["cannot"]) for p in plan] == [("DEU", "no subtitle to translate from")]
    row = controller.review["rows"][0]
    assert (row["state"], row["warning"]) == ("look", "DEU subtitle cannot be made: no subtitle to translate from")
    assert controller.review["rows"][1]["state"] == "in"


def test_the_place_draws_without_warnings(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    controller.set_subtitle_choice("approval", "every")
    controller.set_subtitle_choice("output", "new-file")
    add_language(controller, "de")
    settle(controller, qtbot)
    load.window.setProperty("place", "subtitles")
    assert load() == []
    controller.set_subtitle_choice("sync", "alass")
    assert load() == []
    controller.set_subtitle_choice("sync", "ffsubsync")
    assert load() == []
    assert shown(load, "syncSetting_ffsubsync.max_offset") is not None
    load.window.setProperty("place", "review")
    assert load() == []
    assert qt_warnings() == []


def test_subtitles_written_beside_ask_for_no_new_file_and_name_their_file(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    add_language(controller, "de")
    controller.set_subtitle_choice("output", "new-file")
    settle(controller, qtbot)
    output = row(controller, "output")
    assert output["value"] == "new-file"
    assert [c["label"] for c in output["choices"]] == [
        "Into the video",
        "Beside, replacing the file",
        "Beside, as a new file",
    ]
    assert "subtitles.output" in controller.field_marks
    first = library.items[0].file.path
    (plan,) = controller.subtitles["files"][0]["plan"]
    assert plan["steps"] == f"translate → {first.stem}.de.srt"
    group = next(g for g in controller.review["groups"] if g["key"] == "subtitles")
    # Ten translations, and no new video for them.
    assert [(line["label"], line["count"]) for line in group["lines"]] == [("Finished subtitles", 10)]
    detail = controller.review["rows"][0]["detail"]
    sentences = [line["text"] for line in detail if line["label"] == "Subtitle files"]
    assert sentences == [f"German: written beside the video as {first.stem}.de.srt."]
    assert next(line for line in detail if line["label"] == "File")["after"] == "Stays as it is"


def test_a_translation_says_where_cleanup_runs_in_the_file_list_and_review(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    add_language(controller, "de")
    controller.set_subtitle_choice("output", "new-file")
    settle(controller, qtbot)

    def said() -> tuple[str, list[str]]:
        plan = next(p for p in controller.subtitles["files"][0]["plan"] if p["code"] == "DEU")
        detail = controller.review["rows"][0]["detail"]
        cleanup = [line["text"] for line in detail if line["label"] == "Cleanup" and "German" in line["text"]]
        return plan["steps"].split(" → ")[0], cleanup

    # Nothing cleans either side, and Review says so: the reference's hearing-impaired text would be translated.
    assert said() == (
        "translate",
        ["No rule set cleans the reference before it is translated · No rule set cleans the German translation"],
    )
    controller.add_rule_set("no-sdh")
    settle(controller, qtbot)
    assert said() == (
        "clean the reference · translate · clean",
        [
            "The reference is cleaned with Hearing impaired before it is translated · German is cleaned with"
            " Hearing impaired"
        ],
    )


def test_the_translate_row_translates_always_and_names_the_ai_file(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    add_language(controller, "de")
    controller.set_subtitle_choice("output", "new-file")
    controller.set_subtitle_choice("translate", "always")
    settle(controller, qtbot)
    translate = row(controller, "translate")
    assert translate["value"] == "always"
    assert [c["label"] for c in translate["choices"]] == ["When missing", "Always"]
    assert "subtitles.translate" in controller.field_marks
    first = library.items[0].file.path
    (plan,) = controller.subtitles["files"][0]["plan"]
    assert plan["steps"] == f"translate → {first.stem}_ai.de.srt"
    # Turkish, which the episodes have already, is translated next to it.
    add_language(controller, "tr")
    settle(controller, qtbot)
    turkish = next(p for p in controller.subtitles["files"][0]["plan"] if p["code"] == "TUR")
    assert turkish["steps"] == f"translate · next to the existing one → {first.stem}_ai.tr.srt"


def test_a_bad_new_file_text_blocks_the_subtitle_plans_and_says_why(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    assert controller.save_profile_as("Series") == ""
    controller.settings.open("profiles")
    controller.settings.set_new_file_text("a/b")
    add_language(controller, "de")
    controller.set_subtitle_choice("output", "new-file")
    settle(controller, qtbot)
    assert controller.workspace_tabs[2]["count"] == 0
    group = next(g for g in controller.review["groups"] if g["key"] == "subtitles")
    assert group["problems"][0].startswith("The text for new subtitle files")


def shown(load: Any, name: str) -> QQuickItem | None:
    """The item of that name among the visible children of the window: delegates of a Repeater are not found by
    `findChild`, which walks the object tree."""
    pending = [load.window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    return None


def fields(controller: WindowController) -> dict[str, dict[str, Any]]:
    return {f["key"]: f for f in row(controller, "sync")["settings"]}


def test_the_sync_row_shows_the_engines_settings_by_place(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    assert "settings" in row(controller, "sync")
    assert row(controller, "sync")["settings"] == []  # no engine chosen: nothing to set
    controller.set_subtitle_choice("sync", "ffsubsync")
    shown = fields(controller)
    assert list(shown) == [
        "ffsubsync.in_sync_below",
        "ffsubsync.unsure_below",
        "ffsubsync.max_offset",
        "ffsubsync.framerate",
        "ffsubsync.vad",
    ]
    # Nothing set: the engine's own value is the placeholder, the field is empty and unmarked.
    low = shown["ffsubsync.unsure_below"]
    assert (low["value"], low["placeholder"], low["own"], low["number"]) == ("", "0.1", False, True)
    assert [c["key"] for c in shown["ffsubsync.vad"]["choices"]] == ["", "auditok"]
    controller.set_setting("ffsubsync.max_offset", "30")
    controller.set_setting("ffsubsync.in_sync_below", "soon")  # no number: not taken
    controller.set_setting("ffsubsync.in_sync_below", "-1")
    controller.set_setting("ffsubsync.vad", "auditok")
    shown = fields(controller)
    assert (shown["ffsubsync.max_offset"]["value"], shown["ffsubsync.max_offset"]["own"]) == ("30", True)
    assert shown["ffsubsync.in_sync_below"]["value"] == ""
    assert shown["ffsubsync.vad"]["current"] == "auditok"
    # The season receives them, marked, with the show's value as the placeholder.
    controller.select(season)
    settle(controller, qtbot)
    received = fields(controller)["ffsubsync.max_offset"]
    assert (received["value"], received["placeholder"], received["own"]) == ("", "30", False)
    assert received["mark"] == {"from": "From the show", "over": ""}
    # Its own value overrides, and emptying the field gives the show's back.
    controller.set_setting("ffsubsync.max_offset", "90")
    own = fields(controller)["ffsubsync.max_offset"]
    assert (own["value"], own["own"], own["mark"]["over"]) == ("90", True, "Overrides the show")
    controller.set_setting("ffsubsync.max_offset", "")
    assert fields(controller)["ffsubsync.max_offset"]["own"] is False
    assert fields(controller)["ffsubsync.max_offset"]["placeholder"] == "30"
    # Following the show again on the Sync row takes the season's own settings away with its engine.
    controller.set_setting("ffsubsync.max_offset", "90")
    controller.follow_subtitles("sync")
    assert fields(controller)["ffsubsync.max_offset"]["own"] is False
    # Another engine has no settings in this version.
    controller.set_subtitle_choice("sync", "alass")
    assert row(controller, "sync")["settings"] == []


def test_a_field_of_the_engines_settings_is_typed_into_and_read_again(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    controller.set_subtitle_choice("sync", "ffsubsync")
    settle(controller, qtbot)
    load.window.setProperty("place", "subtitles")
    load()
    field = shown(load, "syncSetting_ffsubsync.max_offset")
    assert field is not None

    def type_in(text: str) -> None:
        field.setProperty("text", text)
        QMetaObject.invokeMethod(field, "editingFinished")
        load()

    # A decimal comma is read as a point, a word is refused and the field shows what is kept, and emptying it gives
    # the engine's own value back.
    type_in("1,5")
    assert fields(controller)["ffsubsync.max_offset"]["value"] == "1.5"
    assert field.property("text") == "1.5"
    type_in("soon")
    assert fields(controller)["ffsubsync.max_offset"]["value"] == "1.5"
    assert field.property("text") == "1.5"
    type_in("")
    assert fields(controller)["ffsubsync.max_offset"]["own"] is False
    assert field.property("text") == ""
    assert field.property("placeholderText") == "60"


def test_kept_names_are_typed_on_the_show_and_taken_back_on_a_season(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    controller.add_translation_name("  Town\n Square ")
    controller.add_translation_name("   ")
    qtbot.waitUntil(lambda: [item["label"] for item in row(controller, "names")["items"]] == ["Town Square"])
    names = row(controller, "names")
    assert names["kept"] == f"{library.items[2].identity.show} is always kept"
    assert names["help"] == "subtitles_names"

    controller.select(season)
    qtbot.waitUntil(lambda: row(controller, "names")["items"][0]["mark"]["from"] == "From the show")
    assert row(controller, "names")["items"][0]["off"] is False
    controller.toggle_subtitle_item("names", "Town Square")
    qtbot.waitUntil(lambda: row(controller, "names")["items"][0]["off"] is True)
    assert row(controller, "names")["items"][0]["mark"]["over"] == "Overrides the show"


def lines_fields(controller: WindowController) -> dict[str, dict[str, Any]]:
    return {f["key"]: f for f in row(controller, "lines")["settings"]}


def test_the_lines_row_shows_the_chosen_way_s_settings_by_place(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    assert row(controller, "lines")["settings"] == []  # as they are: nothing to set
    controller.set_subtitle_choice("lines", "resplit")
    timing = ["timing.longest_line", "timing.two_lines_from", "timing.smallest_overlap", "timing.punctuation"]
    assert list(lines_fields(controller)) == timing
    shown = lines_fields(controller)
    assert (shown["timing.longest_line"]["placeholder"], shown["timing.longest_line"]["label"]) == (
        "42",
        "Longest line (characters)",
    )
    assert [c["key"] for c in shown["timing.punctuation"]["choices"]] == ["", "weak", "strong"]
    # With AI adds its own window, its default translation's window in Settings.
    controller.set_subtitle_choice("lines", "ai")
    assert list(lines_fields(controller)) == [*timing, "ai.window"]
    assert lines_fields(controller)["ai.window"]["placeholder"] == "40"
    # A value out of its range is not taken; one in it is, and the season receives it.
    controller.set_setting("timing.longest_line", "10")
    assert lines_fields(controller)["timing.longest_line"]["value"] == ""
    controller.set_setting("timing.longest_line", "37")
    controller.set_setting("timing.smallest_overlap", "0,5")  # a decimal comma
    controller.set_setting("timing.punctuation", "strong")
    shown = lines_fields(controller)
    assert (shown["timing.longest_line"]["value"], shown["timing.smallest_overlap"]["value"]) == ("37", "0.5")
    assert shown["timing.punctuation"]["current"] == "strong"
    controller.select(season)
    settle(controller, qtbot)
    received = lines_fields(controller)["timing.longest_line"]
    assert (received["value"], received["placeholder"], received["mark"]["from"]) == ("", "37", "From the show")
    # Following the show again on the Lines row takes the season's own settings away with its way.
    controller.set_setting("timing.longest_line", "50")
    controller.follow_subtitles("lines")
    assert lines_fields(controller)["timing.longest_line"]["own"] is False
