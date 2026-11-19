"""The Tracks strip and the width it has: each track's label stands still while the strip of files scrolls sideways
under it, a narrow place takes the labels' short form, and where every file would not fit the strip folds the runs
of files that follow every track, until the user picks."""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.ui.quick.window import WindowController
from showrunner.ui.theme.tokens import SIZES

from .conftest import long_show
from .test_qml import _all, _item, _items


def open_matrix(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot, width: int
) -> tuple[QQuickItem, QQuickItem]:
    """The first season open on Tracks in a window `width` wide; returns the matrix and its list of track rows."""
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)).parent())
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setWidth(width)
    load.window.setProperty("place", "tracks")
    assert load() == []
    root = load.window.contentItem()
    return _item(root, "matrix"), _item(root, "trackRows")


def scene_x(item: QQuickItem) -> float:
    return item.mapToScene(QPointF()).x()


def cells(rows: QQuickItem) -> list[QQuickItem]:
    """The first track's cells, left to right."""
    line = min((i for i in _items(rows, "trackLine") if i.isVisible()), key=lambda i: i.property("index"))
    return sorted((c for c in _items(line, "stripCell") if c.isVisible()), key=scene_x)


def sideways_bar(rows: QQuickItem) -> QQuickItem | None:
    """The horizontal scrollbar of `rows` when it shows."""
    bars = [
        i
        for i in _all(rows)
        if i.metaObject().className().startswith("Scroller") and i.property("orientation") == Qt.Orientation.Horizontal
    ]
    shown = [b for b in bars if b.isVisible()]
    return shown[0] if shown else None


def test_a_season_that_fits_shows_every_file_beside_the_full_labels(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    matrix, rows = open_matrix(load, controller, library, qtbot, 1920)
    assert (matrix.property("brief"), matrix.property("folded")) == (False, False)
    strip = cells(rows)
    assert len(strip) == 10
    assert {c.width() for c in strip} == {SIZES["strip_pitch"]}
    assert scene_x(strip[0]) - scene_x(rows) == SIZES["track_strip_label"]
    assert rows.property("contentWidth") <= rows.width()
    assert sideways_bar(rows) is None


def test_a_long_season_folds_until_every_file_is_asked_for_and_then_scrolls_beside_fixed_labels(
    load: Any, controller: WindowController, qtbot: QtBot
) -> None:
    matrix, rows = open_matrix(load, controller, long_show(1, 40), qtbot, 1440)
    assert matrix.property("folded") is True  # 40 files do not fit: the runs fold, as no choice was made
    matrix.setProperty("chosen", "all")
    load()
    assert matrix.property("folded") is False
    assert rows.property("contentWidth") > rows.width()
    assert sideways_bar(rows) is not None
    labels = [c for c in _items(rows, "chip0") if c.isVisible()]
    assert labels
    # Scrolled sideways, the cells move and the label stays; the cells built follow the files in view.
    second = lambda: next(c for c in cells(rows) if c.property("at") == 1)  # noqa: E731
    label_at, cell_at = scene_x(labels[0]), scene_x(second())
    rows.setProperty("contentX", SIZES["strip_pitch"])
    assert load() == []
    assert scene_x(labels[0]) == label_at
    assert scene_x(second()) == cell_at - SIZES["strip_pitch"]
    assert min(c.property("at") for c in cells(rows)) == 1


def test_a_narrow_place_takes_the_short_labels(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    matrix, rows = open_matrix(load, controller, library, qtbot, SIZES["window_min_width"])
    assert matrix.width() < SIZES["strip_label_short_below"]
    assert matrix.property("brief") is True
    assert scene_x(cells(rows)[0]) - scene_x(rows) == SIZES["track_strip_label_narrow"]


@pytest.mark.parametrize("width", [1440, 1920])
def test_the_codecs_are_not_cut_at_a_normal_window(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot, width: int
) -> None:
    _matrix, rows = open_matrix(load, controller, library, qtbot, width)
    codecs = [i for i in _items(rows, "labelCodec") if i.isVisible() and i.property("text")]
    assert len(codecs) == len(controller.matrix["headers"])
    assert not [i.property("text") for i in codecs if i.property("truncated")]
