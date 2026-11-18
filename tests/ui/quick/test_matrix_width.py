"""The Tracks matrix and the width it has: the columns share it down to one minimum, below which the matrix scrolls
sideways with the file names staying put, and neither names nor column labels are cut where there is room."""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.ui.quick.window import WindowController
from showrunner.ui.theme.tokens import SIZES

from .test_qml import _all, _items


def open_matrix(load: Any, controller: WindowController, library: Library, qtbot: QtBot, width: int) -> QQuickItem:
    """The first season open on Tracks in a window `width` wide; returns the matrix's row list."""
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(library.items[2].file.path)).parent())
    qtbot.waitUntil(lambda: not controller.planning)
    load.window.setWidth(width)
    load.window.setProperty("place", "tracks")
    assert load() == []
    (rows,) = (r for r in _items(load.window.contentItem(), "matrixRows") if r.isVisible())
    return rows


def headers(rows: QQuickItem) -> list[QQuickItem]:
    found = [h for h in _items(rows, "matrixHeader") if h.isVisible()]
    return sorted(found, key=lambda h: h.mapToScene(QPointF()).x())


def scene_x(item: QQuickItem) -> float:
    return item.mapToScene(QPointF()).x()


def sideways_bar(rows: QQuickItem) -> QQuickItem | None:
    """The horizontal scrollbar of `rows` when it shows."""
    bars = [
        i
        for i in _all(rows)
        if i.metaObject().className().startswith("Scroller") and i.property("orientation") == Qt.Orientation.Horizontal
    ]
    shown = [b for b in bars if b.isVisible()]
    return shown[0] if shown else None


def test_the_columns_share_a_wide_window_and_nothing_scrolls_sideways(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    rows = open_matrix(load, controller, library, qtbot, 1920)
    heads = headers(rows)
    widths = {h.width() for h in heads}
    assert len(widths) == 1  # one width for every column
    (width,) = widths
    assert width > SIZES["matrix_column_min"]
    # The names take their widest share, the columns the rest of the view less the vertical scrollbar.
    first = scene_x(heads[0]) - scene_x(rows)
    assert first == SIZES["matrix_name"]
    room = rows.width() - rows.property("rightMargin")
    # Only the pixels lost to rounding are left over.
    assert room - SIZES["matrix_name"] - len(heads) * width < len(heads)
    assert rows.property("contentWidth") <= rows.width()
    assert sideways_bar(rows) is None


def test_a_narrow_window_keeps_the_column_minimum_and_scrolls_sideways_beside_fixed_names(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    rows = open_matrix(load, controller, library, qtbot, SIZES["window_min_width"])
    heads = headers(rows)
    assert {h.width() for h in heads} == {SIZES["matrix_column_min"]}
    assert rows.property("contentWidth") > rows.width()
    assert sideways_bar(rows) is not None
    # The names give up their extra room before the columns go under their minimum.
    names = [n for n in _items(rows, "matrixName") if n.isVisible()]
    assert names
    first = scene_x(heads[0]) - scene_x(rows)
    assert first == SIZES["matrix_label"]
    # Scrolled sideways, the track columns move and the file names and the column's cut edge stay.
    name_at, head_at = scene_x(names[0]), scene_x(heads[0])
    rows.setProperty("contentX", SIZES["matrix_column_min"])
    assert load() == []
    assert scene_x(names[0]) == name_at
    assert scene_x(heads[0]) == head_at - SIZES["matrix_column_min"]


@pytest.mark.parametrize("width", [1440, 1920])
def test_names_and_column_labels_are_not_cut_at_a_normal_window(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot, width: int
) -> None:
    rows = open_matrix(load, controller, library, qtbot, width)
    shown = [n for n in _items(rows, "matrixName") if n.isVisible()]
    assert shown
    labels = [
        i for name in ("headerTitle", "headerName") for i in _items(rows, name) if i.isVisible() and i.property("text")
    ]
    assert labels
    assert not [i.property("text") for i in shown + labels if i.property("truncated")]
