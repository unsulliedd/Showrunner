"""Home's recent folders and their menu, Close folder, the window's kept place, and the File title note on Names."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.app.settings.app_settings import load_settings
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.window import WindowController

from .conftest import close_engine
from .test_choices import open_season, settle
from .test_discard import _all, _click, _evaluate


def _shown(root: Any, name: str) -> list[Any]:
    return [i for i in _all(root) if i.objectName() == name and i.isVisible()]


def test_a_recent_folder_is_removed_from_its_menu_and_stays_on_disk(
    load: Any, controller: WindowController, qtbot: QtBot, tmp_path: Path
) -> None:
    kept, gone = tmp_path / "Show Name (2020)", tmp_path / "Movie Name (2019)"
    kept.mkdir()
    gone.mkdir()
    controller.folders._recent = {str(kept): "2026-01-02T00:00:00", str(gone): "2026-01-01T00:00:00"}
    controller.recent_changed.emit()
    load()
    window, root = load.window, load.window.contentItem()
    _, second = _shown(root, "recentRow")
    menu = second.findChild(QObject, "recentMenu")
    assert not menu.property("visible")
    _click(window, second, Qt.MouseButton.RightButton)
    qtbot.waitUntil(lambda: bool(menu.property("visible")))
    assert [_evaluate(menu, f"itemAt({i})").property("text") for i in range(2)] == ["Open", "Remove from recent"]
    _click(window, _evaluate(menu, "itemAt(1)"))
    qtbot.waitUntil(lambda: len(_shown(root, "recentRow")) == 1)
    assert [e["name"] for e in controller.recent] == ["Show Name (2020)"]
    assert gone.is_dir()


def test_close_folder_is_there_only_with_a_folder_open_and_goes_back_to_home(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    root = load.window.contentItem()
    assert _shown(root, "closeFolder") == []
    open_season(controller, library, qtbot)
    settle(controller, qtbot)
    load()
    (button,) = _shown(root, "closeFolder")
    assert button.isEnabled()
    _click(load.window, button)
    qtbot.waitUntil(lambda: not controller.loaded)
    assert _shown(root, "closeFolder") == []
    assert load() == []


def test_the_window_place_is_saved_after_a_move_and_on_closing(load: Any, qtbot: QtBot) -> None:
    load()
    load.window.setProperty("width", 1111)
    qtbot.waitUntil(lambda: ",1111," in load_settings().value.window_geometry)
    load.window.setProperty("height", 777)
    load.run("placeTimer.save()")  # as on closing: at once
    assert load_settings().value.window_geometry.split(",")[2:] == ["1111", "777", "0"]


def test_the_window_opens_where_it_was_left(qapp: QApplication, qtbot: QtBot) -> None:
    controller = WindowController(screens=lambda: [(0, 0, 1920, 1040)])
    controller.save_window_state(40, 50, 1300, 800, False)
    engine = build_engine(controller)
    window = engine.rootObjects()[0]
    qtbot.waitUntil(window.isExposed)
    assert (window.x(), window.y(), window.width(), window.height()) == (40, 50, 1300, 800)
    close_engine(engine, qtbot)
    controller.deleteLater()


def test_the_file_title_card_says_it_is_not_the_file_name(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    settle(controller, qtbot)
    load.window.setProperty("place", "names")
    load()
    (note,) = _shown(load.window.contentItem(), "titleNote")
    assert note.property("text") == "The title stored inside the file, not the file's name. Files are not renamed here."
    controller.pick_template("audio_track_template")
    qtbot.waitUntil(lambda: not _shown(load.window.contentItem(), "titleNote"))
