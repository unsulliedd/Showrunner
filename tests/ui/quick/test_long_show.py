"""A whole show of 300 episodes: what one place shows is built only while it shows or when read, a focus click
rebuilds no rows, and the Tracks strip builds only the files in view and keeps its place."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject
from PySide6.QtQuick import QQuickItem
from pytestqt.qtbot import QtBot

from showrunner.ui.quick import names, window
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.tracks import BatchView
from showrunner.ui.quick.window import WindowController

from .conftest import COMMENTARY, long_show
from .test_choices import settle


def open_show(controller: WindowController, qtbot: QtBot) -> None:
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    controller.model.set_library(long_show())
    controller.select(controller.tree.index(0, 0))
    settle(controller, qtbot)
    assert (controller.batch_kind, len(controller._items)) == ("show", 300)
    assert Path(controller.focus_path).name == controller.inspector["file"]  # the row the Inspector shows is marked


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
    root.findChild(QQuickItem, "matrix").setProperty("chosen", "all")
    qtbot.wait(50)
    rows = root.findChild(QQuickItem, "trackRows")
    assert rows.property("count") == len(controller.matrix["headers"])
    assert len(controller.matrix["strip"]["all"]["files"]) == 300
    assert 0 < len(_named(rows, "stripNumber")) < 100  # only the files in view are built
    rows.setProperty("contentX", 3000.0)
    controller.pause_rule(0, True)  # a choice gives the strip new cells of the same batch
    settle(controller, qtbot)
    qtbot.wait(50)
    assert rows.property("contentX") == 3000.0
    assert 0 < len(_named(rows, "stripNumber")) < 100
    assert (built["names"], built["review"]) == (0, 0)
    root.close()
    engine.deleteLater()


def _named(root: QQuickItem, name: str) -> list[QQuickItem]:
    """Items called `name` under `root` in the visual tree, where delegates live."""
    found = [root] if root.objectName() == name else []
    for child in root.childItems():
        found += _named(child, name)
    return found


def _bars(view: QQuickItem) -> list[QQuickItem]:
    return [item for item in view.childItems() if item.metaObject().className().startswith("Scroller")]


def test_long_lists_show_a_scrollbar_and_keep_their_place(controller: WindowController, qtbot: QtBot) -> None:
    engine = build_engine(controller)
    root = engine.rootObjects()[0]
    qtbot.waitUntil(root.isExposed)
    open_show(controller, qtbot)
    tree = root.findChild(QQuickItem, "libraryTree")
    QMetaObject.invokeMethod(tree, "expandRecursively", Q_ARG(int, -1), Q_ARG(int, -1))
    rows = root.findChild(QQuickItem, "overviewRows")
    # Expanding 300 rows is laid out over a few frames, more of them on a busy machine.
    for view in (tree, rows):
        qtbot.waitUntil(lambda view=view: [bar.isVisible() for bar in _bars(view)] == [True], timeout=5_000)
    rows.setProperty("contentY", 3000.0)
    controller.toggle_keep(COMMENTARY)  # a choice gives Overview new rows of the same batch
    settle(controller, qtbot)
    qtbot.wait(50)
    assert rows.property("contentY") == 3000.0
    root.setProperty("place", "review")
    qtbot.wait(50)
    files = root.findChild(QQuickItem, "reviewFiles")
    files.setProperty("contentY", 3000.0)
    controller.set_file_in_run(str(controller._items[100].file.path), False)
    settle(controller, qtbot)
    qtbot.wait(50)
    assert files.property("contentY") == 3000.0
    root.setProperty("place", "names")
    controller.start_template("title_template")
    settle(controller, qtbot)
    qtbot.wait(50)
    named = root.findChild(QQuickItem, "nameRows")
    named.setProperty("contentY", 3000.0)
    controller.focus_file(str(controller._items[70].file.path))  # a click on a row moves the focus
    qtbot.wait(50)
    assert named.property("contentY") == 3000.0
    root.setProperty("place", "tracks")
    qtbot.wait(50)
    matrix = root.findChild(QQuickItem, "trackRows")
    assert any(bar.isVisible() for bar in _bars(matrix))  # the strip of 300 files scrolls sideways
    root.close()
    engine.deleteLater()


def test_another_batch_with_as_many_rows_starts_at_the_top(controller: WindowController, qtbot: QtBot) -> None:
    engine = build_engine(controller)
    root = engine.rootObjects()[0]
    qtbot.waitUntil(root.isExposed)
    open_show(controller, qtbot)
    show = controller.tree.index(0, 0)
    seasons = [controller.tree.index(row, 0, show) for row in (0, 1)]  # 25 episodes each
    for season in seasons:  # Names lists rows only under a template
        controller.select(season)
        controller.start_template("title_template")
    root.findChild(QQuickItem, "matrix").setProperty("chosen", "all")
    # The Tracks strip runs sideways: another batch starts at its first file.
    for place, name, axis in (("overview", "overviewRows", "contentY"), ("tracks", "trackRows", "contentX"),
                              ("review", "reviewFiles", "contentY"), ("names", "nameRows", "contentY")):  # fmt: skip
        root.setProperty("place", place)
        controller.select(seasons[0])
        settle(controller, qtbot)
        qtbot.wait(50)
        view = root.findChild(QQuickItem, name)
        top = view.property(axis)
        view.setProperty(axis, top + 100.0)
        assert view.property(axis) == top + 100.0, place
        controller.select(seasons[1])
        settle(controller, qtbot)
        qtbot.wait(50)
        assert view.property(axis) == top, place
    root.close()
    engine.deleteLater()


def test_lists_that_shrink_while_they_show_read_no_missing_row(controller: WindowController, qtbot: QtBot) -> None:
    warnings: list[str] = []
    engine = build_engine(controller, on_warnings=lambda errors: warnings.extend(e.toString() for e in errors))
    root = engine.rootObjects()[0]
    qtbot.waitUntil(root.isExposed)
    open_show(controller, qtbot)
    root.setProperty("place", "review")
    controller.set_file_in_run(str(controller._items[3].file.path), False)
    settle(controller, qtbot)
    controller.review_filter = "out"  # 300 cards become 1
    qtbot.wait(50)
    controller.review_filter = "all"
    qtbot.wait(50)
    root.setProperty("place", "names")
    controller.start_template("title_template")
    settle(controller, qtbot)
    qtbot.wait(50)
    controller.clear_template()  # 300 rows become none
    settle(controller, qtbot)
    qtbot.wait(50)
    controller.model.set_library(long_show(1, 5))  # the overview of another batch with fewer rows
    root.setProperty("place", "overview")
    controller.select(controller.tree.index(0, 0))
    settle(controller, qtbot)
    qtbot.wait(50)
    assert warnings == []
    root.close()
    engine.deleteLater()


def test_many_chips_leave_the_file_list_its_room(controller: WindowController, qtbot: QtBot) -> None:
    from dataclasses import replace

    show = long_show(2, 10, named_per_episode=True)
    items = tuple(
        replace(i, file=replace(i.file, tracks=(*i.file.tracks, *(replace(t, id=t.id + 10) for t in i.file.tracks))))
        for i in show.items
    )  # every track twice in its file, so each group is told apart by name and every episode's tracks are chips
    engine = build_engine(controller)
    root = engine.rootObjects()[0]
    qtbot.waitUntil(root.isExposed)
    controller.start()
    controller.model.set_library(replace(show, items=items))
    controller.select(controller.tree.index(0, 0))
    settle(controller, qtbot)
    qtbot.wait(50)
    groups = root.findChild(QQuickItem, "chipGroups")
    rows = root.findChild(QQuickItem, "overviewRows")
    assert groups.property("contentHeight") > groups.height()  # the chips scroll inside their box
    assert rows.height() > 0
    root.close()
    engine.deleteLater()
