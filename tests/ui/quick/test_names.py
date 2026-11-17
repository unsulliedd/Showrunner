"""The Names place through the controller: templates and custom tokens edited in the batch's working copy as
template text, planned live and counted like every other choice."""

from __future__ import annotations

from dataclasses import replace

from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.core.naming import CustomKind, NamingOptions
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.ui.quick.window import WindowController

from .conftest import program_statuses
from .test_choices import open_season, settle


def naming(controller: WindowController) -> NamingOptions:
    assert controller._key is not None
    return controller.batches.profile(controller._key).for_stage("naming")


def test_opening_names_writes_nothing(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    assert [c["empty"] for c in controller.names["cards"]] == [True] * 4
    assert controller.names["title"] == "Episode titles"
    assert not controller.profile_edited


def test_a_suggestion_then_chips_build_the_template(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.start_template("title_template")
    assert naming(controller).title_template == "{file_name}"
    assert controller.batches.own(controller._key)  # type: ignore[arg-type]
    controller.rail_remove(0)
    for token in ("show", "season", "episode", "episode_title"):
        controller.rail_append(token)
    controller.rail_add_text(1, " - S")
    controller.rail_add_text(3, "E")
    controller.rail_add_text(5, " - ")
    controller.rail_optional(6)
    controller.rail_padding(2)
    controller.rail_padding(4)
    assert naming(controller).title_template == "{show} - S{season:00}E{episode:00}[ - {episode_title}]"
    settle(controller, qtbot)
    title = controller.names["cards"][0]
    assert (title["sample"], title["count"], title["count_text"]) == (
        "Show Name - S01E01 - Episode One",
        10,
        "10 titles",
    )
    tabs = {tab["key"]: tab["count"] for tab in controller.workspace_tabs}
    assert tabs["names"] == 10
    controller.clear_template()
    assert naming(controller).title_template == ""


def test_a_drop_onto_the_rail_moves_or_inserts(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.pick_template("audio_track_template")
    assert controller.names["title"] == "Audio track names"
    controller.rail_insert(0, "language")
    controller.rail_insert(1, "channels")
    controller.rail_add_text(1, " ")
    controller.rail_move(2, 0)
    assert naming(controller).audio_track_template == "{channels}{language} "
    assert naming(controller).title_template == ""


def test_custom_tokens_are_made_edited_renamed_and_removed(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.add_token()
    assert controller.tokens["editor"]["name"] == "token_1"
    controller.set_token_kind(0, "pattern")
    controller.set_token_text(0, r"(S\d+)")
    controller.rail_append("token_1")
    assert controller.tokens["editor"]["found"] == "10 of 10"
    controller.rename_token(0, "code")
    (token,) = naming(controller).custom_tokens
    assert (token.name, token.kind, token.text) == ("code", CustomKind.PATTERN, r"(S\d+)")
    assert naming(controller).title_template == "{code}"
    assert controller.names["rail"][1]["known"] is True
    controller.edit_token(-1)
    assert controller.tokens["editor"] == {}
    controller.edit_token(0)
    controller.remove_token(0)
    assert (naming(controller).custom_tokens, controller.tokens["editor"]) == ([], {})
    assert controller.names["problems"] == ["Unknown token {code}."]


def test_a_problem_elsewhere_is_shown_in_names(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.pick_template("subtitle_track_template")
    controller.rail_append("nothing_here")
    controller.pick_template("title_template")
    controller.start_template("title_template")
    settle(controller, qtbot)
    assert controller.names["blocked"] == ["Subtitle track names: Unknown token {nothing_here}."]
    assert [c["problem"] for c in controller.names["cards"]] == [False, False, False, True]
    assert {tab["key"]: tab["count"] for tab in controller.workspace_tabs}["names"] == 0


def test_the_token_search_filters_the_panel(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.token_query = "codec"
    found = [t["name"] for g in controller.tokens["groups"] for t in g["tokens"]]
    assert found == ["video_codec", "codec"]


def test_rows_say_why_the_plan_writes_no_name(library: Library, qtbot: QtBot, opened: list[str]) -> None:
    def without_mkvtoolnix() -> dict[str, DependencyStatus]:
        return {**program_statuses(), "mkvtoolnix": DependencyStatus("mkvtoolnix", State.MISSING)}

    controller = WindowController(statuses=without_mkvtoolnix, get_program=opened.append)
    open_season(controller, library, qtbot)
    controller.start_template("title_template")
    settle(controller, qtbot)
    (row, *_rest) = controller.names["rows"]
    assert (row["changed"], row["note"]) == (
        False,
        "MKVToolNix is needed to write names; until then this file keeps its names",
    )
    assert controller.names["cards"][0]["count"] == 0
    controller.deleteLater()


def test_a_file_that_is_not_matroska_keeps_its_names(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    items = list(library.items)
    items[0] = replace(items[0], file=replace(items[0].file, container="mp4"))
    open_season(controller, replace(library, items=tuple(items)), qtbot)
    controller.start_template("title_template")
    settle(controller, qtbot)
    first, second = controller.names["rows"][:2]
    assert (first["changed"], first["note"]) == (False, "Only Matroska files take names; this file keeps its names")
    assert (second["changed"], second["note"]) == (True, "")
    assert controller.names["cards"][0]["count"] == 9


def test_a_removed_token_takes_its_value_map_and_the_editor_follows_the_batch(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.add_token()
    assert controller._key is not None
    copy = controller.batches.copy(controller._key)
    copy.set_options("naming", replace(naming(controller), value_maps={"token_1": {"a": "b"}, "show": {"x": "y"}}))
    controller.focus_file(str(library.items[4].file.path))
    assert controller.tokens["editor"]["name"] == "token_1"  # a row of the same season keeps it open
    controller.remove_token(0)
    assert naming(controller).value_maps == {"show": {"x": "y"}}
    controller.add_token()
    controller.select(controller.tree.index_of(str(library.items[12].file.path)).parent())
    assert controller.tokens["editor"] == {}
