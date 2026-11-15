"""A whole show of 300 episodes: what one place shows is built only while it shows or when read, a focus click
rebuilds no rows, and the track matrix creates rows only as they scroll into view and keeps its place."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from showrunner.ui.quick import names, window
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.tracks import BatchView
from showrunner.ui.quick.window import WindowController

from .conftest import long_show
from .test_choices import settle

COMMENTARY = 2


def open_show(controller: WindowController, qtbot: QtBot) -> None:
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    controller.model.set_library(long_show())
    controller.select(controller.tree.index(0, 0))
    settle(controller, qtbot)
    assert (controller.batch_kind, len(controller._items)) == ("show", 300)


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    """How often the Names place, Review and the batch's rows were built."""
    calls: Counter[str] = Counter()

    def counted(name: str, build: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls[name] += 1
            return build(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(names, "place", counted("names", names.place))
    monkeypatch.setattr(window, "review", counted("review", window.review))
    monkeypatch.setattr(BatchView, "rows", counted("rows", BatchView.rows))
    return calls


def test_names_and_review_are_built_only_while_they_show(
    controller: WindowController, qtbot: QtBot, built: Counter[str]
) -> None:
    open_show(controller, qtbot)
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    assert (built["names"], built["review"]) == (0, 0)
    assert controller.change_count == 300  # the top bar's count needs no Review cards
    with qtbot.waitSignal(controller.names_changed):
        controller.show_place("names")
    assert built["names"] == 1
    with qtbot.waitSignal(controller.review_changed):
        controller.show_place("review")
    assert controller.review["count"] == controller.change_count
    controller.review  # noqa: B018  # a second read is the built one
    assert built["review"] == 1


def test_a_hidden_place_still_reads_as_it_is(controller: WindowController, qtbot: QtBot) -> None:
    open_show(controller, qtbot)
    controller.toggle_keep(COMMENTARY)
    controller.start_template("title_template")
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["state"] == "dropped"
    assert len(controller.names["rows"]) == 300
    assert controller.review["count"] == controller.change_count > 300


def test_a_focus_click_rebuilds_no_rows(controller: WindowController, qtbot: QtBot, built: Counter[str]) -> None:
    open_show(controller, qtbot)
    rows = controller.overview["rows"]
    before = built["rows"]
    controller.focus_file(rows[40]["path"])  # in a whole show only the focus moves
    assert controller.focus_path == rows[40]["path"]
    assert controller.inspector["file"] == Path(rows[40]["path"]).name
    assert controller.overview["rows"] == rows
    assert built["rows"] == before


def test_the_window_builds_only_the_place_it_shows(
    controller: WindowController, qtbot: QtBot, built: Counter[str]
) -> None:
    engine = build_engine(controller)
    root = engine.rootObjects()[0]
    qtbot.waitUntil(root.isExposed)
    open_show(controller, qtbot)
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    assert (built["names"], built["review"]) == (0, 0)  # Overview shows: no hidden place reads its data
    root.setProperty("place", "tracks")
    qtbot.wait(50)
    rows = root.findChild(QQuickItem, "matrixRows")
    assert rows.property("count") == 300
    assert 0 < len(rows.property("contentItem").childItems()) < 100  # rows are created as they scroll into view
    rows.setProperty("contentY", 3000.0)
    controller.pause_rule(0, True)  # a choice gives the matrix new rows of the same batch
    settle(controller, qtbot)
    qtbot.wait(50)
    assert rows.property("contentY") == 3000.0
    assert (built["names"], built["review"]) == (0, 0)
    root.close()
    engine.deleteLater()
