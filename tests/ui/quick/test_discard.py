"""Discard changes: the question names the place and what goes, the discard clears the place and everything inside it
so it follows what is above again, and the library row's menu, the header and the keyboard reach it."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QModelIndex, QObject, QPointF, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.app.storage.paths import workspace_path
from showrunner.ui.quick.window import WindowController

from .test_choices import COMMENTARY, open_season, settle


def _places() -> list[dict[str, Any]] | None:
    """The places the workspace file holds, once it is written."""
    path = workspace_path()
    return json.loads(path.read_text(encoding="utf-8"))["batches"]["places"] if path.is_file() else None


def _own_choice_in_season_and_episode(controller: WindowController, library: Library, qtbot: QtBot) -> QModelIndex:
    """The open season holds a choice of its own, and so does its third episode."""
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.toggle_keep(COMMENTARY)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    settle(controller, qtbot)
    controller.toggle_keep(COMMENTARY)
    controller.select(season)
    settle(controller, qtbot)
    return season


def test_nothing_to_discard_on_a_place_that_follows_its_parent(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert not controller.can_discard
    assert controller.place_actions == [{"key": "discard", "text": "Discard changes", "enabled": False}]
    asked: list[bool] = []
    controller.discard_asked.connect(lambda: asked.append(True))
    controller.ask_discard()
    assert asked == []


def test_the_question_names_the_place_and_what_goes_and_a_season_clears_its_episodes(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    _own_choice_in_season_and_episode(controller, library, qtbot)
    assert controller.can_discard
    asked: list[bool] = []
    controller.discard_asked.connect(lambda: asked.append(True))
    controller.ask_discard()
    assert asked == [True]
    question = controller.discard_question
    assert question["heading"] == "Discard changes on Season 1 of Show Name (2020)?"
    assert question["text"] == (
        "Season 1 loses 1 choice of its own and follows the show again.\n\n"
        "Everything set in 1 place inside Season 1 goes too (1 choice).\n\n"
        "This cannot be undone."
    )
    controller.discard_changes()
    settle(controller, qtbot)
    assert not controller.can_discard
    assert controller.rules == []
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    settle(controller, qtbot)
    assert controller.rules == []
    qtbot.waitUntil(lambda: _places() == [])  # saved as after any other change


def test_discarding_a_show_returns_its_profile_and_clears_its_seasons_and_says_so(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    season = _own_choice_in_season_and_episode(controller, library, qtbot)
    controller.select(season.parent())
    settle(controller, qtbot)
    controller.toggle_keep(COMMENTARY)
    assert controller.profile_edited
    text = controller.discard_question["text"]
    assert "loses its unsaved edits of the profile “Default” and goes back to it as saved" in text
    assert "Everything set in 2 places inside" in text
    assert "goes too (2 choices)" in text
    assert text.endswith("This cannot be undone.")
    controller.discard_changes()
    settle(controller, qtbot)
    assert not controller.profile_edited
    assert not controller.can_discard
    assert controller.rules == []
    qtbot.waitUntil(lambda: _places() == [])


def test_a_movie_names_the_movies_group_as_the_place_it_follows_again(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot, episode=-1)  # the last item of the library is a movie
    assert controller.batch_kind == "movie"
    controller.toggle_keep(COMMENTARY)
    assert "follows the Movies group again" in controller.discard_question["text"]
    controller.discard_changes()
    settle(controller, qtbot)
    assert not controller.can_discard


def _all(root: QQuickItem) -> list[QQuickItem]:
    found = [root]
    for child in root.childItems():
        found += _all(child)
    return found


def _visible(root: QQuickItem, name: str) -> QQuickItem:
    (found,) = (item for item in _all(root) if item.objectName() == name and item.isVisible())
    return found


def _row(root: QQuickItem, row_id: str) -> QQuickItem:
    """The visible library row with `row_id`."""
    (found,) = (i for i in _all(root) if i.isVisible() and i.property("row_id") == row_id)
    return found


def _named(window: Any, name: str) -> QObject:
    found = window.findChild(QObject, name)
    assert found is not None, name
    return found


def _evaluate(target: QObject, source: str) -> Any:
    expression = QQmlExpression(QQmlEngine.contextForObject(target), target, source)
    value = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return value[0] if isinstance(value, tuple) else value


def _click(window: Any, item: QQuickItem, button: Qt.MouseButton = Qt.MouseButton.LeftButton) -> None:
    point = item.mapToScene(QPointF(item.width() / 2, min(item.height() / 2, 12))).toPoint()
    QTest.mouseClick(window, button, Qt.KeyboardModifier.NoModifier, point)


def test_a_right_click_on_a_row_opens_its_menu_and_discard_asks_before_it_clears(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    _own_choice_in_season_and_episode(controller, library, qtbot)
    season = controller.selected
    controller.select(controller.tree.index(0, 0))  # another place is open; the right-click selects the season
    settle(controller, qtbot)
    load()
    window, root = load.window, load.window.contentItem()
    menu = _named(window, "libraryMenu")
    assert not menu.property("visible")
    _click(window, _row(root, season), Qt.MouseButton.RightButton)
    qtbot.waitUntil(lambda: bool(menu.property("visible")))
    assert controller.batch["title"] == "Season 1"
    entry = _evaluate(menu, "itemAt(0)")
    assert (entry.property("text"), entry.property("enabled")) == ("Discard changes", True)
    popup = _named(window, "discardPopup")
    _click(window, entry)
    qtbot.waitUntil(lambda: bool(popup.property("visible")))
    assert popup.property("heading") == "Discard changes on Season 1 of Show Name (2020)?"
    assert controller.can_discard  # asking changes nothing
    QTest.keyClick(window, Qt.Key.Key_Escape)  # No
    qtbot.waitUntil(lambda: not popup.property("visible"))
    assert controller.can_discard
    controller.ask_discard()
    qtbot.waitUntil(lambda: bool(popup.property("visible")))
    _click(window, _visible(root, "confirmYes"))
    qtbot.waitUntil(lambda: not controller.can_discard)
    assert load() == []


def test_the_header_button_follows_whether_there_is_something_to_discard(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    load()
    window, root = load.window, load.window.contentItem()
    assert not [item for item in _all(root) if item.objectName() == "discardBatch" and item.isVisible()]  # Review only
    window.setProperty("place", "review")
    button = _visible(root, "discardBatch")
    assert not button.property("enabled")
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    load()
    assert button.property("enabled")
    popup = _named(window, "discardPopup")
    _click(window, button)
    qtbot.waitUntil(lambda: bool(popup.property("visible")))
    assert load() == []


def test_the_menu_key_and_shift_f10_open_the_menu_of_the_selected_row(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    load()
    window = load.window
    menu = _named(window, "libraryMenu")
    _visible(window.contentItem(), "libraryTree").forceActiveFocus()
    for key, modifier in (
        (Qt.Key.Key_Menu, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier),
    ):
        QTest.keyClick(window, key, modifier)
        qtbot.waitUntil(lambda: bool(menu.property("visible")))
        QTest.keyClick(window, Qt.Key.Key_Escape)
        qtbot.waitUntil(lambda: not menu.property("visible"))
    assert load() == []


def test_the_shortcuts_list_the_keys_that_open_the_row_menu(controller: WindowController) -> None:
    entries = {entry["text"]: entry["keys"] for entry in controller.settings.shortcuts}
    assert len(entries["Library: open the menu of the selected row"]) == 2
