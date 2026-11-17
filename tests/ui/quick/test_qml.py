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


def _open_lists(root: QQuickItem) -> list[QQuickItem]:
    """The name lists of the chips that are folded open."""
    return [i for i in _items(root, "chipNameRows") if i.isVisible()]


def _top(item: QQuickItem) -> float:
    return item.mapToScene(QPointF(0, 0)).y()


def _bottom(item: QQuickItem) -> float:
    return item.mapToScene(QPointF(0, item.height())).y()


def _left(item: QQuickItem) -> float:
    return item.mapToScene(QPointF(0, 0)).x()


def _contains(outer: QQuickItem, inner: QQuickItem) -> bool:
    return (
        _top(outer) <= _top(inner)
        and _bottom(inner) <= _bottom(outer)
        and _left(outer) <= _left(inner)
        and _right(inner) <= _right(outer)
    )


def _overlap(one: QQuickItem, other: QQuickItem) -> bool:
    return (
        _left(one) < _right(other)
        and _left(other) < _right(one)
        and _top(one) < _bottom(other)
        and _top(other) < _bottom(one)
    )


def _named_show(load: Any, controller: WindowController, qtbot: QtBot, episodes: int = 10) -> QQuickItem:
    """Episodes with every track named after its episode, one of them selected; the window's root item."""
    from .conftest import long_show  # imported here: a test below runs this module's imports in a child process

    show = long_show(1, episodes, named_per_episode=True)
    load()
    controller.start()
    controller.model.set_library(show)
    controller.select(controller.tree.index_of(str(show.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    return load.window.contentItem()


def test_a_chip_s_arrow_folds_the_chip_open_and_leaves_the_chip_alone(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _named_show(load, controller, qtbot)
    assert len(controller.overview["groups"][0]["chips"]) == 4  # tracks named per episode are one chip each
    assert _open_lists(root) == []
    chip = _item(root, "chip1")
    closed = (chip.width(), chip.height())
    _click(load.window, _item(chip, "namesButton"))
    load()
    (rows,) = _open_lists(root)
    assert chip.property("namesOpen") is True
    assert rows.property("count") == 9  # Episode Seven has no Turkish audio
    assert chip.property("rows")[0] == "01 · Long Show - 1x01 - Episode One (Turkish)"
    assert chip.property("missing") == "Missing in 07"
    assert controller.rules == []  # only the arrow answered, not the chip
    # The list is inside the chip's own frame, under its header, and the frame has grown for it.
    assert _top(rows) >= _bottom(_item(chip, "chipHeader"))
    assert _contains(chip, rows)
    assert chip.height() > closed[1]
    assert closed[0] <= chip.width() <= _item(root, "chipGroups").width()
    # The chips around it are as they were, and no chip lies over another where the Flow placed them again.
    assert _item(root, "chip0").height() == closed[1]
    chips = [_item(root, f"chip{i}") for i in range(8)]
    assert not any(_overlap(a, b) for i, a in enumerate(chips) for b in chips[i + 1 :])
    # One at a time: another chip's arrow switches, a second click closes, also from the other kind of track.
    _click(load.window, _item(_item(root, "chip0"), "namesButton"))
    load()
    (rows,) = _open_lists(root)
    assert (rows.property("count"), _item(root, "chip0").property("missing")) == (10, "")
    assert chip.height() == closed[1]
    _click(load.window, _item(_item(root, "chip0"), "namesButton"))
    load()
    assert _open_lists(root) == []
    _click(load.window, _item(_item(root, "chip4"), "namesButton"))
    load()
    (rows,) = _open_lists(root)
    assert _contains(_item(root, "chip4"), rows)
    _click(load.window, _item(_item(root, "chip0"), "namesButton"))
    load()
    (rows,) = _open_lists(root)
    assert _contains(_item(root, "chip0"), rows)
    assert _item(root, "chip4").height() == closed[1]
    _click(load.window, _item(_item(root, "chip0"), "namesButton"))
    load()
    assert _open_lists(root) == []
    assert controller.rules == []
    # A click on the rest of the header still drops the track, with the list open.
    _click(load.window, _item(chip, "namesButton"))
    load()
    header = _item(chip, "chipHeader")
    QTest.mouseClick(
        load.window,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        header.mapToScene(QPointF(header.width() / 3, header.height() / 2)).toPoint(),
    )
    load()
    assert len(controller.rules) == 1
    assert len(_open_lists(root)) == 1
    # Another batch closes the list.
    controller.select(controller.tree.index_of(str(controller.model.library.items[0].file.path)).parent().parent())
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    assert _open_lists(root) == []
    assert load() == []
    assert qt_warnings() == []


def test_a_long_list_is_capped_inside_the_chip_and_scrolls(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _named_show(load, controller, qtbot, episodes=40)
    chip = _item(root, "chip1")
    closed = chip.height()
    _click(load.window, _item(chip, "namesButton"))
    load()
    (rows,) = _open_lists(root)
    assert rows.property("count") == 39
    assert rows.height() == SIZES["names_height"]
    assert rows.property("contentHeight") > SIZES["names_height"]
    assert chip.height() == closed + SIZES["names_height"] + SIZES["space_md"]
    assert _contains(chip, rows)
    # Scrolled to its end the list shows the line for the files without the track.
    assert rows.property("atYEnd") is False
    rows.setProperty("contentY", rows.property("contentHeight") - rows.height())
    load()
    assert rows.property("atYEnd") is True
    assert load() == []
    assert qt_warnings() == []


def test_a_matrix_header_s_arrow_still_opens_the_popup(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _named_show(load, controller, qtbot)
    load.window.setProperty("place", "tracks")
    load()
    arrows = sorted((b for b in _items(root, "namesButton") if b.isVisible()), key=_right)
    _click(load.window, arrows[0])
    load()
    assert len(_names_popup(load.window).property("rows").toVariant()) == 10
    assert controller.rules == []
    _click(load.window, arrows[0])  # closes the list
    # The header of a track some files lack ends its list with the files that do.
    _click(load.window, arrows[1])
    load()
    rows = _names_popup(load.window).property("rows").toVariant()  # a list the popup built itself
    assert (len(rows), rows[-1]) == (10, "Missing in 07")
    assert load() == []
    assert qt_warnings() == []


def test_a_chip_keeps_even_room_on_both_sides_in_every_state_and_ends_with_its_arrow(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    root = load.window.contentItem()
    room = SIZES["space_md"]

    def check() -> int:
        found = 0
        for index in range(sum(len(group["chips"]) for group in controller.overview["groups"])):
            chip = next((c for c in _items(root, f"chip{index}") if c.isVisible()), None)
            if chip is None:
                continue
            found += 1
            header = _item(chip, "chipHeader")
            content = header.property("contentItem")
            assert content.x() == room, index
            assert header.width() - content.x() - content.width() == room, index
            assert header.width() == chip.width(), index
            for part in content.childItems():
                if part.isVisible() and part.height() > 0:  # not the spacer before the arrow
                    assert part.x() >= 0, (index, part)
                    assert part.x() + part.width() <= content.width() + 0.5, (index, part)
            arrows = [b for b in _items(chip, "namesButton") if b.isVisible()]
            if arrows:
                # Both are children of the header's row; the arrow turns up when open, so measure by position.
                flags = [f for f in _items(chip, "defaultFlag") if f.isVisible()]
                assert all(f.x() < arrows[0].x() for f in flags)
                assert header.width() - (content.x() + arrows[0].x() + arrows[0].width()) == room, index
        return found

    assert check() == 8
    # Dropped, and a paired file added.
    controller.toggle_keep(2)
    controller.toggle_keep(7)
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    assert check() == 8
    # At the narrowest window the long names are cut short, the arrow and the room stay.
    load.window.setWidth(1024)
    qtbot.waitUntil(lambda: load.window.width() == 1024)
    qtbot.wait(300)
    assert check() == 8
    # An open chip has widened for its names; its arrow still ends it, with the same room.
    _click(load.window, _item(_item(root, "chip1"), "namesButton"))
    load()
    assert check() == 8
    assert load() == []
    assert qt_warnings() == []


def test_an_open_chip_stays_inside_the_tracks_box_at_the_narrowest_window(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _named_show(load, controller, qtbot)
    load.window.setWidth(1024)
    qtbot.waitUntil(lambda: load.window.width() == 1024)
    qtbot.wait(300)
    rightmost = max((b for b in _items(root, "namesButton") if b.isVisible()), key=_right)
    assert _right(rightmost) <= _right(_item(root, "chipGroups"))  # a long name is cut short, the arrow stays in
    _click(load.window, rightmost)
    load()
    (rows,) = _open_lists(root)
    chip = rows.parentItem().parentItem()  # the foldout, then the chip that holds it
    assert _contains(chip, rows)
    assert _right(chip) <= _right(_item(root, "chipGroups"))
    assert _right(chip) <= load.window.width()
    assert load() == []
    assert qt_warnings() == []


def test_a_chip_folds_open_inside_its_row_at_a_narrow_a_laptop_and_a_wide_window(
    load: Any, controller: WindowController, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _named_show(load, controller, qtbot)
    for width in (1024, 1280, 1920):
        load.window.setWidth(width)
        qtbot.waitUntil(lambda width=width: load.window.width() == width)
        qtbot.wait(300)
        groups = _item(root, "chipGroups")
        room = _right(groups) - SIZES["scroll_thumb"] - 2 * SIZES["space_xs"]  # what the scroll view leaves the row
        chips = [_item(root, f"chip{i}") for i in range(8)]
        # The first, a middle and the last chip of every row of the flow, closed and open.
        rows: dict[int, list[QQuickItem]] = {}
        for chip in chips:
            rows.setdefault(round(_top(chip)), []).append(chip)
        picks = {c.objectName(): c for row in rows.values() for c in (min(row, key=_left), max(row, key=_left))}
        picks.update({row[len(row) // 2].objectName(): row[len(row) // 2] for row in rows.values()})
        for name in sorted(picks):
            chip = _item(root, name)
            arrows = [a for a in _items(chip, "namesButton") if a.isVisible()]
            if not arrows or _bottom(arrows[0]) > _bottom(groups):
                continue  # the paired file every episode has gives no list; or scrolled out of the box
            arrow = arrows[0]
            _click(load.window, arrow)
            load()
            (rows_list,) = _open_lists(root)
            assert _contains(chip, rows_list), (width, name)
            assert _right(chip) <= room + 0.5, (width, name)
            assert _left(chip) >= _left(groups), (width, name)
            assert _right(_item(chip, "namesButton")) <= _right(chip), (width, name)
            now = [_item(root, f"chip{i}") for i in range(8)]
            assert not any(_overlap(a, b) for i, a in enumerate(now) for b in now[i + 1 :]), (width, name)
            _click(load.window, _item(chip, "namesButton"))
            load()
            assert _open_lists(root) == []
    assert load() == []
    assert qt_warnings() == []


def test_a_chip_stays_open_through_a_resize_and_the_separator_with_a_height_already_saved(
    saved_height: int,
    load: Any,
    controller: WindowController,
    library: Library,
    qt_warnings: Any,
    qtbot: QtBot,
) -> None:
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    root = load.window.contentItem()
    _click(load.window, _item(_item(root, "chip1"), "namesButton"))
    load()
    box, bar, rows = (_item(root, name) for name in ("tracksBox", "tracksSeparator", "overviewRows"))
    for width, height in ((1024, 640), (1920, 1080), (1280, 800), (1024, 640)):
        load.window.setWidth(width)
        load.window.setHeight(height)
        qtbot.waitUntil(
            lambda width=width, height=height: (load.window.width(), load.window.height()) == (width, height)
        )
        qtbot.wait(300)
        assert len(_open_lists(root)) == 1, (width, height)  # the open chip keeps its contents
        assert _contains(_item(root, "chip1"), _open_lists(root)[0])
        assert box.height() >= SIZES["tracks_min_height"]  # the saved height is clamped, never zero
        assert rows.height() >= SIZES["rows_min_height"]
        assert _bottom(rows) <= load.window.height()
    # The separator to its two ends with the chip open.
    _drag_by(load.window, qtbot, bar, 100)
    load()
    assert rows.height() == SIZES["rows_min_height"]
    _drag_by(load.window, qtbot, bar, -300)
    load()
    assert box.height() == SIZES["tracks_min_height"]
    assert len(_open_lists(root)) == 1
    assert load() == []
    assert qt_warnings() == []


def _drag_by(window: Any, qtbot: QtBot, item: QQuickItem, dy: int) -> None:
    start = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    steps = 8
    for step in range(1, steps + 1):
        QTest.mouseMove(window, QPoint(start.x(), start.y() + dy * step // steps))
        qtbot.wait(10)
    QTest.mouseRelease(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(start.x(), start.y() + dy)
    )


def test_the_separator_sets_the_height_of_the_tracks_box_and_keeps_it(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    from showrunner.app.settings.app_settings import load_settings

    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    root = load.window.contentItem()
    box, bar, rows = (_item(root, name) for name in ("tracksBox", "tracksSeparator", "overviewRows"))
    fitted = box.height()
    assert load_settings().value.overview_tracks_height == 0  # nothing chosen: the box fits its chips
    # Drag it down: the box grows by as much as the pointer moved, the file list gives way, the choice is saved.
    _drag_by(load.window, qtbot, bar, 40)
    load()
    assert box.height() == fitted + 40
    assert load_settings().value.overview_tracks_height == box.height()
    # As far as it goes either way, neither side vanishes.
    _drag_by(load.window, qtbot, bar, 300)
    load()
    assert rows.height() == SIZES["rows_min_height"]  # the file list keeps its room
    assert box.height() > fitted + 40
    _drag_by(load.window, qtbot, bar, -400)
    load()
    assert box.height() == SIZES["tracks_min_height"]
    assert rows.height() > SIZES["rows_min_height"]
    # The keyboard moves it by a step and keeps the result when the key is let go.
    bar.forceActiveFocus()
    QTest.keyClick(load.window, Qt.Key.Key_Down)
    load()
    assert box.height() == SIZES["tracks_min_height"] + SIZES["separator_step"]
    assert load_settings().value.overview_tracks_height == box.height()
    QTest.keyClick(load.window, Qt.Key.Key_Up)
    QTest.keyClick(load.window, Qt.Key.Key_Up)
    load()
    assert box.height() == SIZES["tracks_min_height"]
    assert load() == []
    assert qt_warnings() == []


@pytest.fixture
def saved_height(controller: WindowController) -> int:
    """A height saved before the window loads, since the window reads it once, when its Overview is made."""
    controller.save_overview_tracks_height(300)
    return 300


def test_a_saved_height_of_the_tracks_box_is_used_when_the_window_opens(
    saved_height: int,
    load: Any,
    controller: WindowController,
    library: Library,
    qt_warnings: Any,
    qtbot: QtBot,
) -> None:
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    assert _item(load.window.contentItem(), "tracksBox").height() == saved_height
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


def test_the_job_list_shrinks_and_clears_without_warnings(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path, qt_warnings: Any
) -> None:
    """A second job with fewer files while the first one's rows show, then Clear: each row reads its own file."""
    from .test_apply import make_setup

    made = make_setup(qtbot, tmp_path, fail="Show.Name.S01E")  # every check fails, so the files stay as read
    controller = made.controller
    warnings: list[str] = []
    engine = build_engine(controller, on_warnings=lambda errors: warnings.extend(e.toString() for e in errors))
    window = engine.rootObjects()[0]
    qtbot.waitUntil(window.isExposed)
    root = window.contentItem()
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    qtbot.waitUntil(lambda: _item(root, "jobRows").property("count") == 10)
    for path in made.season[3:]:
        controller.leave_out_file(str(path), True)
    qtbot.waitUntil(lambda: not controller.planning and controller.can_apply)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    qtbot.waitUntil(lambda: _item(root, "jobRows").property("count") == 3)
    controller.jobs.clear()
    qtbot.waitUntil(lambda: not _items(root, "jobRows")[0].isVisible())
    qtbot.wait(50)
    assert warnings == []
    assert qt_warnings() == []
    window.close()
    engine.deleteLater()
    controller.deleteLater()


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


def _drag_from(window: Any, qtbot: QtBot, item: QQuickItem, dx: int, dy: int) -> None:
    """A real pointer drag from the centre of `item` by (dx, dy)."""
    start = _centre(item)
    _drag(window, qtbot, start, QPoint(start.x() + dx, start.y() + dy))


def _grips(root: QQuickItem, name: str, axis: str) -> list[QQuickItem]:
    grips = [g for g in _items(root, name) if g.isVisible()]
    return sorted(grips, key=lambda g: getattr(g.mapToScene(QPointF()), axis)())


def test_matrix_columns_move_by_drag_and_by_keyboard(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setProperty("place", "tracks")
    load()
    root = load.window.contentItem()
    codes = lambda: [h["code"] for h in controller.matrix["headers"]]  # noqa: E731
    assert codes()[:4] == ["ENG", "TUR", "ENG", "ENG"]
    grips = _grips(root, "columnGrip", "x")
    # Every column of the sample has a grip: each kind has more than one.
    assert len(grips) == len(controller.matrix["headers"])
    assert grips[1].property("activeFocusOnTab") is True
    # Drag the Turkish column one column to the left.
    _drag_from(load.window, qtbot, grips[1], -SIZES["matrix_column"], 0)
    load()
    assert codes()[:2] == ["TUR", "ENG"]
    # Ctrl+Right on the focused grip moves it one place, and the focus follows the column.
    grips = _grips(root, "columnGrip", "x")
    grips[0].forceActiveFocus()
    QTest.keyClick(load.window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    load()
    assert codes()[:2] == ["ENG", "TUR"]
    grips = _grips(root, "columnGrip", "x")
    assert grips[1].hasActiveFocus()
    QTest.keyClick(load.window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    load()
    assert codes()[:3] == ["ENG", "ENG", "TUR"]
    assert _grips(root, "columnGrip", "x")[2].hasActiveFocus()
    # Without Ctrl the arrow moves nothing.
    QTest.keyClick(load.window, Qt.Key.Key_Left)
    load()
    assert codes()[:3] == ["ENG", "ENG", "TUR"]
    # A column moved by keyboard past the right edge of a narrow window is scrolled into view.
    load.window.setWidth(1024)
    load()
    first_subtitle = len([h for h in controller.matrix["headers"] if h["kind"] == "audio"])
    _grips(root, "columnGrip", "x")[first_subtitle].forceActiveFocus()
    for _ in range(3):
        QTest.keyClick(load.window, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        load()
    rows = _item(root, "matrixRows")
    focused = next(g for g in _items(root, "columnGrip") if g.hasActiveFocus())
    left = focused.mapToItem(rows, QPointF()).x()
    assert rows.property("contentX") > 0
    assert left >= 0
    assert left + focused.width() <= rows.width()
    assert load() == []
    assert qt_warnings() == []


def _audio_grips(root: QQuickItem) -> list[QQuickItem]:
    """The grips of a movie's audio cards: the left one of the two card columns."""
    grips = _grips(root, "cardGrip", "y")
    left = min(g.mapToScene(QPointF()).x() for g in grips)
    return [g for g in grips if g.mapToScene(QPointF()).x() == left]


def test_movie_track_cards_move_by_drag_and_by_keyboard(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[-3].file.path)))
    qtbot.waitUntil(lambda: not controller.planning)
    load()
    root = load.window.contentItem()
    titles = lambda: [c["title"] for c in controller.movie["groups"][0]["cards"]]  # noqa: E731
    before = titles()
    assert len(before) == 3
    audio = _audio_grips(root)
    assert len(audio) == 3
    # Drag the last audio card two places up.
    step = SIZES["track_card"] + SIZES["space_md"]
    _drag_from(load.window, qtbot, audio[2], 0, -2 * step)
    load()
    assert titles() == [before[2], before[0], before[1]]
    # Ctrl+Down moves the focused card one place down, and the focus follows it.
    audio = _audio_grips(root)
    audio[0].forceActiveFocus()
    QTest.keyClick(load.window, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    load()
    assert titles() == [before[0], before[2], before[1]]
    assert _audio_grips(root)[1].hasActiveFocus()
    QTest.keyClick(load.window, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    load()
    assert titles() == [before[2], before[0], before[1]]
    assert load() == []
    assert qt_warnings() == []
