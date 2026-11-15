"""Every QML file compiles, the window loads in each of its states without a QML warning, and the QML files hold no
literal colors or user-facing text and ask only for string keys that exist."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlEngine, QQmlError, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

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
    keys = {key for key in keys if not key.endswith(".")}
    assert sorted(key for key in keys if key not in catalog) == []
    assert sorted(key for key in plurals if f"{key}.one" not in catalog or f"{key}.other" not in catalog) == []


def test_qml_files_hold_no_literal_colors_or_text() -> None:
    for path in QML_FILES:
        text = path.read_text(encoding="utf-8")
        assert re.findall(r"#[0-9a-fA-F]{3,8}\b", text) == [], path.name
        assert re.findall(r'\b(?:text|title|label|placeholderText): *"[^"]', text) == [], path.name
        assert re.findall(r"\bQt\.(?:rgba|hsla|hsva|lighter|darker)\(", text) == [], path.name
