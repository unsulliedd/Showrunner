"""Every QML file compiles, the window loads in each of its states without a QML warning, and the QML files hold no
literal colors or user-facing text and ask only for string keys that exist."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QQmlEngine, QQmlError, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.batches.batch import BatchKind
from showrunner.app.library.library import Library
from showrunner.tools.probe import Programs
from showrunner.ui.i18n.catalog import STRINGS_DIR
from showrunner.ui.quick import names, palette
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
    assert words == [
        "Drop audio in ENG Dolby Digital 2.0 flagged commentary",
        "Keep audio in TUR Dolby Digital Plus 5.1 · default",
    ]
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
    assert words[-1] == "Drop audio in ENG Dolby Digital 2.0 flagged commentary"
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


def _names_popup(window: Any) -> QObject:
    (opened,) = (p for p in window.findChildren(QObject, "trackNames") if p.property("opened"))
    return opened


def test_a_chip_s_arrow_lists_each_file_s_name_and_leaves_the_chip_alone(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    from .conftest import long_show  # imported here: a test below runs this module's imports in a child process

    show = long_show(1, 10, named_per_episode=True)
    load()
    controller.start()
    controller.model.set_library(show)
    controller.select(controller.tree.index_of(str(show.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    root = load.window.contentItem()
    assert len(controller.overview["groups"][0]["chips"]) == 4  # tracks named per episode are one chip each
    _click(load.window, _item(_item(root, "chip1"), "namesButton"))
    load()
    rows = _names_popup(load.window).property("rows")
    assert len(rows) == 9  # Episode Seven has no Turkish audio
    assert rows[0] == "01 · Long Show - 1x01 - Episode One (Turkish)"
    assert controller.rules == []  # only the arrow answered, not the chip
    _click(load.window, _item(_item(root, "chip1"), "namesButton"))
    load()
    assert not any(p.property("opened") for p in load.window.findChildren(QObject, "trackNames"))
    load.window.setProperty("place", "tracks")
    load()
    header = next(b for b in _items(root, "namesButton") if b.isVisible())
    _click(load.window, header)
    load()
    assert len(_names_popup(load.window).property("rows")) == 10
    assert controller.rules == []
    # At the narrowest window the list under the rightmost arrow moves left to stay inside it.
    _click(load.window, header)  # closes the list
    load.window.setProperty("place", "overview")
    load.window.setWidth(1024)
    qtbot.waitUntil(lambda: load.window.width() == 1024)
    qtbot.wait(300)
    rightmost = max((b for b in _items(root, "namesButton") if b.isVisible()), key=_right)
    assert _right(rightmost) <= _right(_item(root, "chipGroups"))  # a long name is cut short, the arrow stays in
    assert _right(rightmost) + SIZES["names_width"] > load.window.width()  # the list would not fit where it opens
    _click(load.window, rightmost)
    load()
    assert _right(_names_popup(load.window).property("contentItem")) <= load.window.width()
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


def test_review_apply_and_the_job_offer_draw_without_warnings(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, qt_warnings: Any
) -> None:
    """Review with a group and a file left out driven by clicks, Apply from its button, the job in the drawer while
    it holds half way, then finished, and the offer of a cancelled job in a second window."""
    from .conftest import program_statuses
    from .test_apply import COMMENTARY, StandInMux, make_setup

    made = make_setup(qtbot, tmp_path)
    controller = made.controller
    warnings: list[str] = []
    engine = build_engine(controller, on_warnings=lambda errors: warnings.extend(e.toString() for e in errors))
    window = engine.rootObjects()[0]
    qtbot.waitUntil(window.isExposed)
    window.setProperty("place", "review")
    qtbot.wait(50)
    root = window.contentItem()
    controller.start_template("title_template")
    qtbot.waitUntil(lambda: not controller.planning)
    qtbot.wait(50)
    _click(window, _item(root, "inRun_names"))
    qtbot.waitUntil(lambda: not controller.planning and not controller.review["groups"][1]["in_run"])
    qtbot.wait(50)
    _click(window, _items(root, "leaveOut")[1])
    assert controller.left_out.files == {made.season[1]}
    qtbot.wait(50)
    _click(window, _items(root, "expand")[0])
    qtbot.wait(50)
    # With every card open, a card's own toggle still folds it.
    _click(window, _item(root, "expandAll"))
    qtbot.wait(50)
    card = _items(root, "expand")[1].parentItem()
    while "ReviewFile" not in card.metaObject().className():
        card = card.parentItem()
    assert card.property("expanded") is True
    _click(window, _items(root, "expand")[1])
    qtbot.wait(50)
    assert card.property("expanded") is False
    assert warnings == []
    made.hold.clear()
    _click(window, _item(root, "applyButton"))
    qtbot.waitUntil(lambda: controller.jobs.running)
    assert window.property("drawerOpen") is True
    assert _item(root, "jobsPanel").isVisible()
    assert controller.locked
    qtbot.wait(100)
    made.hold.set()
    qtbot.waitUntil(lambda: not controller.applying, timeout=10_000)
    qtbot.wait(100)
    assert [r["state"] for r in controller.jobs.view["rows"]] == ["done"] * 9
    assert warnings == []
    controller.toggle_keep(COMMENTARY)  # unlocked again
    window.close()
    engine.deleteLater()

    # An unfinished job, offered in a new window and discarded there.
    made.hold.clear()
    again = make_setup(qtbot, tmp_path / "again")
    again.hold.clear()
    again.controller.apply()
    qtbot.waitUntil(lambda: again.controller.jobs.running)
    with qtbot.waitSignal(again.controller.jobs.ended, timeout=10_000):
        again.controller.jobs.cancel()
    stage = StandInMux(Path("mkvmerge"), Programs(mkvmerge=Path("mkvmerge")), bin=again.bin)
    after = WindowController(
        statuses=program_statuses, jobs=again.store, make_pipeline=lambda _s: (stage,), get_program=lambda _i: None
    )
    engine = build_engine(after, on_warnings=lambda errors: warnings.extend(e.toString() for e in errors))
    window = engine.rootObjects()[0]
    qtbot.waitUntil(window.isExposed)
    after.start()
    qtbot.waitUntil(lambda: bool(after.jobs.offer))
    qtbot.wait(100)
    popup = window.findChild(QObject, "jobOffer")
    assert popup.property("visible") is True
    _click(window, _item(window.contentItem(), "discardJob"))
    assert after.jobs.offer == {}
    assert again.store.unfinished() == []
    assert warnings == []
    assert qt_warnings() == []
    window.close()
    engine.deleteLater()


def test_escape_on_the_job_offer_asks_next_time(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    from showrunner.app.jobs.store import JobSummary

    load()
    controller.jobs._offers = [(JobSummary(1, 0.0, "First", 3, 1), True), (JobSummary(2, 0.0, "Second", 3, 0), False)]
    controller.jobs.offer_changed.emit()
    popup = load.window.findChild(QObject, "jobOffer")
    qtbot.waitUntil(lambda: popup.property("visible") is True)
    assert controller.jobs.offer["id"] == 1
    QTest.keyClick(load.window, Qt.Key.Key_Escape)
    # Nothing was resumed or discarded: the next offer shows, and after the last one the popup is gone.
    assert (controller.jobs.offer["id"], controller.jobs.running) == (2, False)
    assert popup.property("visible") is True
    QTest.keyClick(load.window, Qt.Key.Key_Escape)
    assert controller.jobs.offer == {}
    qtbot.waitUntil(lambda: popup.property("visible") is False)
    assert load() == []
    assert qt_warnings() == []


def test_the_matrix_rows_are_one_tab_stop_with_arrow_keys(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    from .conftest import long_show

    show = long_show(1, 40)
    load()
    controller.start()
    controller.model.set_library(show)
    controller.select(controller.tree.index(0, 0))
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setProperty("place", "tracks")
    load()
    root = load.window.contentItem()
    stop = _item(root, "matrixRowKeys")
    rows = _item(root, "matrixRows")
    # Tab alone reaches the rows, as one stop, though only some of the 40 rows exist.
    for _ in range(80):
        if stop.property("activeFocus"):
            break
        QTest.keyClick(load.window, Qt.Key.Key_Tab)
    assert stop.property("activeFocus") is True
    assert rows.property("currentIndex") == 0

    def marked() -> list[int]:
        return [r.property("index") for r in _items(root, "matrixRow") if r.property("marked")]

    assert marked() == [0]
    # Down and Up move row by row and scroll to keep the row in view.
    for _ in range(25):
        QTest.keyClick(load.window, Qt.Key.Key_Down)
    assert rows.property("currentIndex") == 25
    assert rows.property("contentY") > 0
    assert marked() == [25]  # the marked row exists, scrolled into view
    QTest.keyClick(load.window, Qt.Key.Key_Up)
    assert rows.property("currentIndex") == 24
    QTest.keyClick(load.window, Qt.Key.Key_End)
    assert rows.property("currentIndex") == 39
    QTest.keyClick(load.window, Qt.Key.Key_Down)
    assert rows.property("currentIndex") == 39  # stops at the last row
    QTest.keyClick(load.window, Qt.Key.Key_Home)
    assert (rows.property("currentIndex"), rows.property("contentY")) == (0, rows.property("originY"))
    # The current row is marked, and Enter focuses its file in the Inspector as a click does.
    QTest.keyClick(load.window, Qt.Key.Key_Down)
    QTest.keyClick(load.window, Qt.Key.Key_Down)
    QTest.keyClick(load.window, Qt.Key.Key_Return)
    assert controller.focus_path == str(show.items[2].file.path)
    assert controller.inspector["file"] == show.items[2].file.path.name
    # A click on a row takes the keyboard there, and the arrows go on from it.
    _click(load.window, next(r for r in _items(root, "matrixRow") if r.property("index") == 5))
    assert (rows.property("currentIndex"), controller.focus_path) == (5, str(show.items[5].file.path))
    QTest.keyClick(load.window, Qt.Key.Key_Down)
    assert marked() == [6]
    # Tab leaves the matrix after the one stop; no row takes the focus on its own.
    QTest.keyClick(load.window, Qt.Key.Key_Tab)
    assert stop.property("activeFocus") is False
    assert not any(r.property("activeFocus") for r in _items(root, "matrixRow"))
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
    # Keys built from a batch kind, a track kind, a flag and the matrix legend.
    keys |= {f"overview.title.{kind}" for kind in BatchKind}
    keys |= {f"matrix.group.{kind}" for kind in ("audio", "subtitle")}
    keys |= {f"tracks.flag_tip.{flag}" for flag in ("default", "forced")}
    keys |= {f"tokens.editor.kind.{kind}" for kind in names.KINDS}
    keys |= {f"tokens.editor.source.{source}" for source in names.SOURCES}
    keys |= {f"matrix.legend.{entry}" for entry in re.findall(r'"(\w+)"', _legend(text))}
    # Keys built from a Settings section, a choice of a segmented control, a base colour and a palette result.
    keys |= {
        f"prefs.appearance.base.{base}{part}" for base in ("neutral", "primary", "accent") for part in ("", ".hint")
    }
    keys |= {f"palette.kind.{kind}" for kind in palette.KINDS}
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


def _drag(window: Any, qtbot: QtBot, start: QPoint, end: QPoint) -> None:
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    steps = 12
    for step in range(1, steps + 1):
        x = start.x() + (end.x() - start.x()) * step // steps
        y = start.y() + (end.y() - start.y()) * step // steps
        QTest.mouseMove(window, QPoint(x, y))
        qtbot.wait(10)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)


def _centre(item: QQuickItem, x: float = 0.5) -> QPoint:
    return item.mapToScene(QPointF(item.width() * x, item.height() / 2)).toPoint()


def test_names_and_tokens_answer_the_pointer(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setProperty("place", "names")
    assert load() == []
    root = load.window.contentItem()

    def naming() -> Any:
        assert controller._key is not None
        return controller.batches.profile(controller._key).for_stage("naming")

    # An empty card's suggestion starts the template.
    _click(load.window, _item(_item(root, "templateCard_title_template"), "startTemplate"))
    load()
    assert naming().title_template == "{file_name}"
    # A token dragged from the panel onto the left half of a chip goes before it.
    _drag(load.window, qtbot, _centre(_item(root, "tokenChip_show")), _centre(_item(root, "railChip_file_name"), 0.2))
    load()
    assert naming().title_template == "{show}{file_name}"
    # A chip dragged onto the free end of the rail moves there; a click on a panel token adds it at the end.
    frame = _item(root, "railFrame")
    end = frame.mapToScene(QPointF(frame.width() - 10, frame.height() / 2)).toPoint()
    _drag(load.window, qtbot, _centre(_item(root, "railChip_show"), 0.3), end)
    load()
    assert naming().title_template == "{file_name}{show}"
    year = _item(root, "tokenChip_year")
    _click(load.window, year)
    load()
    assert naming().title_template == "{file_name}{show}{year}"
    # A new custom token opens in the editor, and its fields are written when left.
    _click(load.window, _item(root, "addToken"))
    load()
    assert controller.tokens["editor"]["name"] == "token_1"
    field = _item(root, "tokenText")
    _click(load.window, field)
    for key in (Qt.Key.Key_G, Qt.Key.Key_R, Qt.Key.Key_P):
        QTest.keyClick(load.window, key)
    QTest.keyClick(load.window, Qt.Key.Key_Return)
    load()
    assert naming().custom_tokens[0].text == "grp"
    assert controller.tokens["editor"]["found"] == "10 of 10"
    # A focused chip shows its buttons: the format steps, the dashed box makes it optional, x takes it out.
    _click(load.window, _item(root, "tokenChip_season"))
    load()
    _click(load.window, _item(root, "railChip_season"))
    load()
    _click(load.window, _item(_item(root, "railChip_season"), "chipFormat"))
    load()
    assert naming().title_template == "{file_name}{show}{year}{season:00}"
    _click(load.window, _item(root, "railChip_year"))
    load()
    _click(load.window, _item(_item(root, "railChip_year"), "chipRemove"))
    load()
    assert naming().title_template == "{file_name}{show}{season:00}"
    _click(load.window, _item(root, "railChip_season"))
    load()
    _click(load.window, _item(_item(root, "railChip_season"), "chipOptional"))
    load()
    assert naming().title_template == "{file_name}{show}[{season:00}]"
    # Text typed into the place before the first chip is written on Enter.
    first = min((s for s in _items(root, "railSlot") if s.isVisible()), key=lambda s: s.mapToScene(QPointF()).x())
    _click(load.window, first)
    QTest.keyClick(load.window, Qt.Key.Key_X)
    QTest.keyClick(load.window, Qt.Key.Key_Return)
    load()
    assert naming().title_template == "x{file_name}{show}[{season:00}]"
    for card in ("video_track_template", "audio_track_template", "subtitle_track_template", "title_template"):
        _click(load.window, _item(root, "templateCard_" + card))
        assert load() == [], card
    # A movie names its title card for movies.
    movie = next(i for i in library.items if i.file.path.name.startswith("Movie.Title"))
    controller.select(controller.tree.index_of(str(movie.file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    assert load() == []
    assert controller.names["title"] == "Movie titles"
    assert qt_warnings() == []


def _key(window: Any, key: Qt.Key, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(window, key, modifier)


def test_settings_and_the_palette_answer_the_keyboard(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    window = load.window
    dialog = window.findChild(QObject, "settings")
    # Ctrl+, opens Settings; Down, End, Home and Up move between sections; Escape closes it.
    _key(window, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: dialog.property("opened"))
    assert dialog.property("section") == "general"
    _key(window, Qt.Key.Key_Down)
    assert dialog.property("section") == "profiles"
    _key(window, Qt.Key.Key_End)
    assert dialog.property("section") == "about"
    _key(window, Qt.Key.Key_Up)
    assert dialog.property("section") == "shortcuts"
    _key(window, Qt.Key.Key_Home)
    assert dialog.property("section") == "general"
    for section in ("profiles", "programs", "appearance", "shortcuts", "about", "general"):
        load.run(f'settings.section = "{section}"')
        assert load() == [], section
    _key(window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not dialog.property("visible"))
    # The pill's Manage profiles opens Profiles; the delete question closes alone on Escape and Settings stays.
    load.run('app.settings.open("profiles")')
    qtbot.waitUntil(lambda: dialog.property("opened"))
    assert dialog.property("section") == "profiles"
    controller.save_profile_as("Series")
    controller.settings.pick("Series")
    load()
    _click(window, _item(window.contentItem(), "deleteProfile"))
    load()
    _key(window, Qt.Key.Key_Escape)
    load()
    assert dialog.property("visible")
    assert "Series" in controller.profiles
    _key(window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not dialog.property("visible"))
    # Ctrl+K focuses the palette; typing searches, Down moves, Return runs.
    _key(window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    field = window.findChild(QQuickItem, "paletteField")
    qtbot.waitUntil(field.hasActiveFocus)
    for letter in "names":
        QTest.keyClick(window, letter)
    load()
    assert controller.palette_query == "names"
    assert controller.palette[0]["key"] == "place.names"
    _key(window, Qt.Key.Key_Return)
    load()
    assert window.property("place") == "names"
    assert controller.palette_query == ""
    assert not field.hasActiveFocus()
    assert load() == []
    assert qt_warnings() == []


def test_a_narrow_compact_window_and_the_palette_by_pointer(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    window = load.window
    window.setWidth(SIZES["window_min_width"])
    controller.look.set_density("compact")
    load()
    # A theme change keeps the window's size.
    assert window.width() == SIZES["window_min_width"]
    dialog = window.findChild(QObject, "settings")
    load.run('settings.show("general")')
    qtbot.waitUntil(lambda: dialog.property("opened"))
    assert dialog.property("rail") is True
    for section in ("general", "profiles", "programs", "appearance", "shortcuts", "about"):
        load.run(f'settings.section = "{section}"')
        assert load() == [], section
    load.run("settings.close()")
    qtbot.waitUntil(lambda: not dialog.property("visible"))
    for place in ("overview", "tracks", "names", "review"):
        window.setProperty("place", place)
        assert load() == [], place
    # A click on a palette result runs it.
    field = window.findChild(QQuickItem, "paletteField")
    _click(window, field)
    for letter in "tracks":
        QTest.keyClick(window, letter)
    load()
    results = _item(window.contentItem(), "paletteResults")
    first = results.property("contentItem").childItems()[0]
    _click(window, first)
    load()
    assert window.property("place") == "tracks"
    assert controller.palette_query == ""
    controller.look.set_density("comfortable")
    assert load() == []
    assert qt_warnings() == []


def _all(item: QQuickItem) -> Iterator[QQuickItem]:
    yield item
    for child in item.childItems():
        yield from _all(child)


def _right(item: QQuickItem) -> float:
    return item.mapToScene(QPointF(item.width(), 0)).x()


@pytest.mark.parametrize("width", [SIZES["window_min_width"], SIZES["settings_rail_below"]])
def test_a_narrow_window_keeps_file_names_and_scrollbars_in_place(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot, width: int
) -> None:
    load()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    window = load.window
    window.setWidth(width)
    assert load() == []
    root = window.contentItem()
    rows = _item(root, "overviewRows")
    # The rows fit their panel and keep room for the file names; the track columns give way first.
    assert _right(rows) <= _right(rows.parentItem().parentItem()) + 1
    names = [i for i in _all(rows) if i.property("text") == library.items[2].identity.episode_title]
    assert names
    assert all(i.width() >= SIZES["matrix_column"] - 1 for i in names)
    # Every scrollbar shown sits on the right edge of its view, never over its top left corner.
    bars = [i for i in _all(root) if i.metaObject().className().startswith("Scroller") and i.isVisible()]
    assert bars
    for bar in bars:
        assert abs(_right(bar) - _right(bar.parentItem())) <= 1, bar.parentItem()


def _left(item: QQuickItem) -> float:
    return item.mapToScene(QPointF(0, 0)).x()


def test_a_narrow_window_elides_text_in_place_and_shows_it_whole_under_the_pointer(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    window = load.window
    window.setWidth(SIZES["window_min_width"])
    window.setProperty("place", "names")
    assert load() == []
    root = window.contentItem()
    # The header's facts end before Leave out.
    facts = next(i for i in _all(root) if i.property("text") == controller.batch["facts"])
    assert _right(facts) <= _left(_item(root, "leaveOutBatch")) + 1
    # A tab of a place that does not exist yet shows whole or not at all.
    tabs = [i for i in _all(root) if i.metaObject().className().startswith("Tabs")]
    for row in tabs:
        for entry in _all(row):
            if entry.property("modelData") is not None and entry.opacity() == 1 and entry.isVisible():
                assert _right(entry) <= _right(row) + 1
    # The template cards keep their text inside; cut text shows whole in a tooltip under the pointer.
    card = _item(root, "templateCard_audio_track_template")
    texts = [i for i in _all(card) if i.metaObject().className().startswith("UiText") and i.isVisible()]
    assert all(_right(i) <= _right(card) + 1 for i in texts)
    cut = next(i for i in texts if i.property("truncated"))
    QTest.mouseMove(window, cut.mapToScene(QPointF(cut.width() / 2, cut.height() / 2)).toPoint())
    qtbot.waitUntil(lambda: _tip(cut).property("visible") is True)
    assert _tip(cut).property("text") == cut.property("text")


def _tip(item: QQuickItem) -> Any:
    expression = QQmlExpression(QQmlEngine.contextForObject(item), item, "ToolTip.toolTip")
    value = expression.evaluate()
    return value[0] if isinstance(value, tuple) else value


# Run in a child process: the layout loop this guards against never returns from Qt's event processing, so in this
# process it would hang the test run instead of failing it.
_SETTLES = """
import os, time
from dataclasses import replace
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from conftest import neutral_library, program_statuses
from showrunner.app.profiles import registered
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.window import WindowController
from showrunner.ui.theme.tokens import SIZES
library = neutral_library()
home = Path(os.environ["SHOWRUNNER_HOME"])
items = tuple(replace(i, file=replace(i.file, path=home / i.file.path)) for i in library.items)
library = replace(library, items=items, alternatives=())
controller = WindowController(statuses=program_statuses)
engine = build_engine(controller)
window = engine.rootObjects()[0]
window.setWidth(SIZES["settings_rail_below"])
window.setHeight(800)  # the narrow size of the bug hunt
controller.start()
controller.model.set_library(library)
controller.select(controller.tree.index_of(str(library.items[0].file.path)))
end = time.monotonic() + 2
while time.monotonic() < end:
    app.processEvents()
print("settled", flush=True)
os._exit(0)
"""


def test_a_narrow_window_settles_with_a_scrolling_inspector(tmp_path: Path) -> None:
    env = os.environ | {"QT_QPA_PLATFORM": "offscreen", "SHOWRUNNER_HOME": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, "-c", _SETTLES],
        cwd=Path(__file__).parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "settled" in done.stdout, done.stderr[-2000:]
