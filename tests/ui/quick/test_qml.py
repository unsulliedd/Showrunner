"""Every QML file compiles, the window loads in each of its states without a QML warning, and the QML files hold no
literal colors or user-facing text and ask only for string keys that exist."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlEngine, QQmlError, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.batches.batch import BatchKind
from showrunner.app.library.library import Library
from showrunner.ui.i18n.catalog import STRINGS_DIR
from showrunner.ui.quick.engine import QML_DIR, build_engine, prepare
from showrunner.ui.quick.window import SIDE_PANELS, WORKSPACE_TABS, WindowController
from showrunner.ui.theme.tokens import SIZES

QML_FILES = sorted(QML_DIR.glob("*.qml"))


@pytest.fixture
def load(controller: WindowController, qtbot: QtBot) -> Iterator[Any]:
    """Load the window; calling the result settles it and gives the QML warnings so far. `window` and `run` (a QML
    expression evaluated in the window's own scope) hang off it. The window closes after the test."""
    warnings: list[str] = []
    engine = build_engine(controller, on_warnings=lambda errors: warnings.extend(e.toString() for e in errors))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    qtbot.waitUntil(window.isExposed)

    def settle() -> list[str]:
        qtbot.wait(50)
        return warnings

    def run(source: str) -> object:
        expression = QQmlExpression(QQmlEngine.contextForObject(window), window, source)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value[0] if isinstance(value, tuple) else value

    settle.window = window  # type: ignore[attr-defined]
    settle.run = run  # type: ignore[attr-defined]
    yield settle
    window.close()
    engine.deleteLater()


@pytest.mark.parametrize("path", QML_FILES, ids=lambda p: p.name)
def test_every_qml_file_compiles(qapp: QApplication, path: Path) -> None:
    prepare()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("app", WindowController())
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    errors: list[QQmlError] = component.errors()
    assert component.isReady(), [e.toString() for e in errors]


def test_the_home_screen_loads_without_warnings(load: Any, controller: WindowController, qt_warnings: Any) -> None:
    controller.start()
    assert load() == []
    assert qt_warnings() == []


def test_a_season_loads_without_warnings(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any
) -> None:
    load()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    assert controller.batch["title"] == "Season 1"
    assert load() == []
    assert qt_warnings() == []


def test_a_movie_loads_without_warnings(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any
) -> None:
    load()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[-3].file.path)))
    assert controller.batch_kind == "movie"
    assert load() == []
    assert qt_warnings() == []


def test_qml_reaches_the_controller(
    load: Any,
    controller: WindowController,
    library: Library,
    qt_warnings: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    load()
    controller.model.set_library(library)
    load()
    # A click on the first row of the tree selects it.
    tree = load.window.findChild(QQuickItem, "libraryTree")
    point = tree.mapToScene(QPointF(tree.width() / 2, SIZES["row_sm"] / 2))
    QTest.mouseClick(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point.toPoint())
    assert controller.selected == controller.tree.row_id(controller.tree.index(0, 0))
    # Dropped URLs arrive as paths.
    dropped: list[list[Path]] = []
    monkeypatch.setattr(controller, "add_paths", dropped.append)
    url = QUrl.fromLocalFile(str(tmp_path)).toString()
    load.run(f'app.add_urls([Qt.resolvedUrl("{url}")])')
    assert dropped == [[tmp_path]]
    # A split saves its sizes and gets them back.
    load.run('app.save_panel_state("columns", columns.saveState())')
    assert not controller.panel_state("columns").isEmpty()
    assert load.run('columns.restoreState(app.panel_state("columns"))') is True
    # Every place, and the drawer pulled up.
    for place in ("tracks", "names", "review", "overview"):
        load.window.setProperty("place", place)
        assert load() == [], place
    load.window.setProperty("drawerOpen", True)
    assert load() == []
    assert qt_warnings() == []


def test_choices_reach_every_place_without_warnings(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    # Chips, flags and rules driven from QML expressions, as a click would.
    load.run("app.toggle_keep(2)")
    load.run('app.toggle_flag(7, "default")')
    load.run("app.pause_rule(0, true)")
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.change_count > 0
    side = load.window.findChild(QQuickItem, "sidePanel")
    for place, tab in (("tracks", "rules"), ("overview", "inspector"), ("tracks", "rules")):
        load.window.setProperty("place", place)
        assert load() == [], place
        assert side.property("tab") == tab, place
    seventh = str(library.items[6].file.path)
    load.run(f"app.focus_file({json.dumps(seventh)})")
    assert controller.focus_path == seventh
    controller.select(controller.tree.index_of(str(library.items[-3].file.path)))
    load.window.setProperty("place", "overview")
    qtbot.waitUntil(lambda: not controller.planning)
    load.run("app.toggle_keep(0)")
    qtbot.waitUntil(lambda: not controller.planning)
    assert load() == []
    assert qt_warnings() == []


def _items(root: QQuickItem, name: str) -> list[QQuickItem]:
    """Items called `name` under `root` in the visual tree, where delegates live (they are no QObject children)."""
    found = [root] if root.objectName() == name else []
    for child in root.childItems():
        found += _items(child, name)
    return found


def _item(root: QQuickItem, name: str) -> QQuickItem:
    (found,) = (item for item in _items(root, name) if item.isVisible())
    return found


def _click(window: Any, item: QQuickItem) -> None:
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def test_chips_and_rules_answer_the_pointer(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    # A click on the commentary chip drops it; a click on the Turkish chip's star sets the default only.
    root = load.window.contentItem()
    _click(load.window, _item(root, "chip2"))
    load()
    _click(load.window, _item(_item(root, "chip1"), "defaultFlag"))
    load()
    words = [" ".join(str(p["text"]) for p in rule["parts"]) for rule in controller.rules]
    assert words == ["Drop audio in ENG named Commentary", "Keep audio in TUR named Turkish · default"]
    controller.toggle_keep(4)
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setProperty("place", "tracks")
    load()
    # Drag the first rule by its grip below the last one.
    grips = sorted((g for g in _items(root, "ruleGrip") if g.isVisible()), key=lambda g: g.mapToScene(QPointF()).y())
    assert len(grips) == 3
    start = grips[0].mapToScene(QPointF(grips[0].width() / 2, grips[0].height() / 2)).toPoint()
    end = grips[2].mapToScene(QPointF(grips[2].width() / 2, grips[2].height() * 2)).toPoint()
    QTest.mousePress(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    steps = 12
    for step in range(1, steps + 1):
        y = start.y() + (end.y() - start.y()) * step // steps
        QTest.mouseMove(load.window, QPoint(start.x(), y))
        qtbot.wait(10)
    QTest.mouseRelease(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    load()
    words = [" ".join(str(p["text"]) for p in rule["parts"]) for rule in controller.rules]
    assert words[-1] == "Drop audio in ENG named Commentary"
    # With more rules than the panel holds the list could scroll; a drag on a grip still moves the rule.
    for column in (5, 6, 7, 3):
        controller.toggle_flag(column, "default")
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    assert len(controller.rules) == 7
    first = controller.rules[0]["parts"]
    grips = sorted((g for g in _items(root, "ruleGrip") if g.isVisible()), key=lambda g: g.mapToScene(QPointF()).y())
    start = grips[0].mapToScene(QPointF(grips[0].width() / 2, grips[0].height() / 2)).toPoint()
    # One card down: the dragged card's centre lands on the second card's centre.
    end = grips[1].mapToScene(QPointF(grips[1].width() / 2, grips[1].height() / 2)).toPoint()
    QTest.mousePress(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, steps + 1):
        QTest.mouseMove(load.window, QPoint(start.x(), start.y() + (end.y() - start.y()) * step // steps))
        qtbot.wait(10)
    QTest.mouseRelease(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    load()
    assert controller.rules[1]["parts"] == first
    assert load() == []
    assert qt_warnings() == []


def test_a_show_and_a_selection_keep_their_batch_when_a_row_is_picked(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    episode = controller.tree.index_of(str(library.items[0].file.path))
    controller.select(episode.parent().parent())
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.batch_kind == "show"
    assert len(controller.overview["rows"]) == 18
    assert load() == []
    load.run(f"app.focus_file({json.dumps(str(library.items[12].file.path))})")
    assert (controller.batch_kind, controller.inspector["name"]) == ("show", "Episode Three")
    movie = controller.tree.index_of(str(library.items[-1].file.path))
    controller.select(movie.parent())
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.batch_kind == "selection"
    load.run(f"app.focus_file({json.dumps(str(library.items[-2].file.path))})")
    assert (controller.batch_kind, controller.inspector["name"]) == ("selection", "Another Movie")
    for place in ("tracks", "overview"):
        load.window.setProperty("place", place)
        assert load() == [], place
    assert qt_warnings() == []


def _qml_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in QML_FILES)


def test_every_string_key_the_qml_asks_for_exists() -> None:
    catalog = json.loads((STRINGS_DIR / "en.json").read_text(encoding="utf-8"))
    text = _qml_text()
    keys = set(re.findall(r'Strings\.[tf]\("([^"]+)"\)', text)) | set(re.findall(r'Strings\.[tf]\("([^"]+)",', text))
    plurals = set(re.findall(r'Strings\.n\("([^"]+)"', text))
    # Keys built from a place's name: one per place that can be opened, and per side panel tab.
    places = [key for key, _icon, later in WORKSPACE_TABS if not later]
    keys |= {f"workspace.tab.{key}" for key, _icon, _later in WORKSPACE_TABS}
    keys |= {f"workspace.placeholder.{place}.{part}" for place in places for part in ("title", "lead")}
    tabs = {tab for panel in SIDE_PANELS.values() for tab in panel}
    keys |= {f"panel.tab.{tab}" for tab in tabs}
    keys |= {f"panel.placeholder.{tab}.{part}" for tab in tabs for part in ("title", "lead")}
    keys |= {f"drawer.placeholder.{tab}.{part}" for tab in ("player", "jobs", "log") for part in ("title", "lead")}
    # Keys built from a batch kind, a track kind, a flag and the matrix legend.
    keys |= {f"overview.title.{kind}" for kind in BatchKind}
    keys |= {f"matrix.group.{kind}" for kind in ("audio", "subtitle")}
    keys |= {f"tracks.flag_tip.{flag}" for flag in ("default", "forced")}
    keys |= {f"matrix.legend.{entry}" for entry in re.findall(r'"(\w+)"', _legend(text))}
    keys = {key for key in keys if not key.endswith(".")}
    assert sorted(key for key in keys if key not in catalog) == []
    assert sorted(key for key in plurals if f"{key}.one" not in catalog or f"{key}.other" not in catalog) == []


def _legend(text: str) -> str:
    """The legend's list of entries in the matrix."""
    found = re.search(r'model: \[("kept"[^\]]*)\]', text)
    assert found is not None
    return found.group(1)


def test_qml_files_hold_no_literal_colors_or_text() -> None:
    for path in QML_FILES:
        text = path.read_text(encoding="utf-8")
        assert re.findall(r"#[0-9a-fA-F]{3,8}\b", text) == [], path.name
        assert re.findall(r'\b(?:text|title|label|placeholderText): *"[^"]', text) == [], path.name
        assert re.findall(r"\bQt\.(?:rgba|hsla|hsva|lighter|darker)\(", text) == [], path.name
