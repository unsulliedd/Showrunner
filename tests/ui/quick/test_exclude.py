"""Exclude and Include: a place out of every run, saved with the workspace. A folder excludes everything inside it, a
place inside can be included again on its own, and Discard, the counts, Review, the menu, the header and the palette
follow."""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QModelIndex, Qt
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.ui.quick.library import EXCLUDED
from showrunner.ui.quick.window import WindowController

from .test_choices import COMMENTARY, open_season, settle
from .test_discard import _all, _click, _evaluate, _named, _row, _visible

EPISODE_SEVEN = 6  # the sample's unsure subtitle file makes it need a look


def open_titled_season(controller: WindowController, library: Library, qtbot: QtBot) -> QModelIndex:
    """The first season open, the show's title template giving every episode a change; returns the season's row."""
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(path_of(library, 2)).parent()
    controller.select(season.parent())
    controller.start_template("title_template")
    controller.select(season)
    settle(controller, qtbot)
    return season


def path_of(library: Library, number: int) -> str:
    return str(library.items[number].file.path)


def marked(controller: WindowController, row_id: str) -> bool:
    return bool(controller.tree.index_of(row_id).data(EXCLUDED))


def season_of(controller: WindowController, library: Library, number: int = 2) -> str:
    return controller.tree.row_id(controller.tree.index_of(path_of(library, number)).parent())


def show_of(controller: WindowController, library: Library, number: int = 2) -> str:
    return controller.tree.row_id(controller.tree.index_of(path_of(library, number)).parent().parent())


def test_excluding_a_season_marks_it_and_its_episodes_and_takes_them_out_of_the_counts(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_titled_season(controller, library, qtbot)
    looks, changes = controller.needs_look, controller.change_count
    assert changes > 0
    assert looks > 0
    assert not controller.place_excluded
    controller.exclude_place(True)
    assert controller.place_excluded
    assert marked(controller, season_of(controller, library))
    assert all(marked(controller, path_of(library, n)) for n in range(10))
    assert not marked(controller, path_of(library, 10))  # season 2
    assert not marked(controller, show_of(controller, library))
    assert (controller.change_count, controller.change_text) == (0, "Nothing to change yet")
    assert controller.needs_look == looks - 1  # Episode Seven no longer needs a look
    assert not controller.can_apply
    assert [t["count"] for t in controller.workspace_tabs if t["key"] in ("tracks", "names", "review")] == [0, 0, 0]
    controller.exclude_place(False)
    assert not marked(controller, season_of(controller, library))
    assert (controller.change_count, controller.needs_look) == (changes, looks)


def test_a_show_excludes_every_season_and_a_season_inside_can_be_included_again_on_its_own(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    season = open_titled_season(controller, library, qtbot)
    controller.select(season.parent())
    settle(controller, qtbot)
    controller.exclude_place(True)
    assert controller.change_count == 0
    controller.select(season)
    settle(controller, qtbot)
    assert controller.place_excluded  # through the show
    assert controller.change_count == 0
    controller.exclude_place(False)
    settle(controller, qtbot)
    assert not controller.place_excluded
    assert controller.change_count > 0
    assert not marked(controller, season_of(controller, library))
    assert not marked(controller, path_of(library, 2))
    assert marked(controller, show_of(controller, library))
    assert marked(controller, season_of(controller, library, 12))  # the show's other season
    controller.select(controller.tree.index_of(path_of(library, 12)))
    assert controller.place_excluded
    # An episode of the included season is excluded on its own, and included again with the season.
    controller.select(controller.tree.index_of(path_of(library, 2)))
    controller.exclude_place(True)
    assert marked(controller, path_of(library, 2))
    assert not marked(controller, path_of(library, 3))


def test_a_movie_can_be_included_inside_the_excluded_movies_group(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot, episode=-1)
    movies = controller.tree.index_of(path_of(library, -1)).parent()
    controller.select(movies)
    settle(controller, qtbot)
    controller.exclude_place(True)
    assert all(marked(controller, path_of(library, n)) for n in (-1, -2, -3))
    controller.select(controller.tree.index_of(path_of(library, -2)))
    assert controller.place_excluded
    controller.exclude_place(False)
    assert not marked(controller, path_of(library, -2))
    assert marked(controller, path_of(library, -1))
    assert marked(controller, controller.tree.row_id(movies))


def test_exclusion_is_saved_with_the_workspace_and_comes_back(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.exclude_place(True)
    controller.save_workspace()
    again = WindowController(statuses=lambda: {})
    try:
        again.model.set_library(library)
        assert marked(again, season_of(controller, library))
        assert marked(again, path_of(library, 4))
        assert not marked(again, path_of(library, 10))
    finally:
        again.deleteLater()


def test_discard_changes_removes_choices_and_leaves_exclusion(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    controller.exclude_place(True)
    assert controller.can_discard
    assert "xclu" not in controller.discard_question["text"]
    controller.discard_changes()
    settle(controller, qtbot)
    assert not controller.can_discard
    assert controller.place_excluded
    # Nothing to discard on an excluded place that holds no choice: exclusion is not one.
    controller.select(controller.tree.index_of(path_of(library, 10)).parent())
    controller.exclude_place(True)
    assert not controller.can_discard


def test_review_lists_an_excluded_file_apart_from_one_left_out_this_time(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.start_template("title_template")
    settle(controller, qtbot)
    every = controller.change_count
    controller.exclude_file(path_of(library, 2), True)
    controller.set_file_in_run(path_of(library, 3), False)
    rows = {r["path"]: r for r in controller.review["rows"]}
    assert (rows[path_of(library, 2)]["state"], rows[path_of(library, 3)]["state"]) == ("excluded", "out")
    assert controller.change_count < every
    filters = {f["key"]: f["count"] for f in controller.review["filters"]}
    assert (filters["run"], filters["out"]) == (8, 2)
    controller.review_filter = "out"
    assert {r["path"] for r in controller.review["rows"]} == {path_of(library, 2), path_of(library, 3)}
    # Not this time is not saved and no part of exclusion: putting the file back leaves the excluded one out.
    controller.set_file_in_run(path_of(library, 3), True)
    assert controller.left_out.empty
    assert marked(controller, path_of(library, 2))
    assert not marked(controller, path_of(library, 3))
    controller.exclude_file(path_of(library, 2), False)
    assert controller.change_count == every


def test_the_menu_and_the_palette_offer_exclude_or_include(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert [a["key"] for a in controller.place_actions] == ["discard", "keep", "exclude"]
    controller.place_action("exclude")
    assert controller.place_excluded
    assert [(a["key"], a["text"]) for a in controller.place_actions] == [
        ("discard", "Discard changes"),
        ("keep", "Keep these files as they are"),
        ("include", "Include"),
    ]
    controller.palette_query = "include"
    assert [(r["key"], r["label"], r["detail"]) for r in controller.palette] == [
        ("include", "Include in the runs again", "Season 1")
    ]
    controller.palette_run("action", "include")
    assert not controller.place_excluded
    controller.palette_query = "exclude"
    assert [r["key"] for r in controller.palette] == ["exclude"]
    controller.palette_run("action", "exclude")
    assert controller.place_excluded


def test_a_place_being_applied_cannot_be_excluded(
    controller: WindowController, library: Library, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    open_season(controller, library, qtbot)
    monkeypatch.setattr(controller, "_locked_paths", lambda: {i.file.path for i in library.items})
    assert next(a for a in controller.place_actions if a["key"] == "exclude")["enabled"] is False
    controller.exclude_place(True)
    assert not controller.place_excluded


def test_the_right_click_menu_and_the_header_exclude_and_the_row_shows_the_mark(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    load()
    window, root = load.window, load.window.contentItem()
    season = controller.selected
    menu = _named(window, "libraryMenu")
    _click(window, _row(root, season), Qt.MouseButton.RightButton)
    qtbot.waitUntil(lambda: bool(menu.property("visible")))
    entry = _evaluate(menu, "itemAt(2)")
    assert (entry.property("text"), entry.property("enabled")) == ("Exclude", True)
    _click(window, entry)
    qtbot.waitUntil(lambda: controller.place_excluded)
    row = _row(root, season)
    assert row.property("excluded") is True
    marks = [i for i in _all(row) if i.objectName() == "excludedMark" and i.isVisible()]
    assert len(marks) == 1
    assert _evaluate(marks[0], "ToolTip.text") == (
        "Excluded: left out of every run. Choose Include in this place's menu to undo it."
    )
    button = _visible(root, "excludeBatch")
    assert button.property("text") == "Include"
    _click(window, button)
    qtbot.waitUntil(lambda: not controller.place_excluded)
    assert button.property("text") == "Exclude"
    assert _row(root, season).property("excluded") is False
    assert load() == []
