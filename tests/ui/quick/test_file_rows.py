"""A track without a name: one line per file under the opened row, a click making that file's own choice at the file's
own place, as a click on the file's cell of the Tracks strip does; the row's Files button, the strip's toolbar and the D
mark that go with it."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from showrunner.app.batches.batch import BatchKey
from showrunner.app.library.library import Library
from showrunner.core.media import Episode
from showrunner.ui.quick.window import WindowController
from showrunner.ui.theme.tokens import SIZES

from .conftest import neutral_library
from .test_choices import COMMENTARY, open_season, settle
from .test_name_rows import _click, _visible, name_rows, season_of, states


def _unnamed(library: Library, upto: int) -> Library:
    """The commentary of the first `upto` episodes loses its name and keeps its flag, so it stays one chip with the
    commentary the other episodes name."""

    def strip(item: Any) -> Any:
        if not isinstance(item.identity, Episode) or item.identity.episode > upto:
            return item
        tracks = tuple(
            replace(t, name="", flags=replace(t.flags, commentary=True)) if t.name == "Commentary" else t
            for t in item.file.tracks
        )
        return replace(item, file=replace(item.file, tracks=tracks))

    return replace(library, items=tuple(strip(i) for i in library.items))


@pytest.fixture
def library() -> Library:
    """Episodes one to three have a commentary without a name, the other seven of the season name theirs."""
    return _unnamed(neutral_library(), 3)


def path_of(library: Library, episode: int) -> str:
    return str(library.items[episode - 1].file.path)


def file_rules(controller: WindowController, library: Library, episode: int) -> list[Any]:
    """The rules the episode's own place holds."""
    assert controller._key is not None
    return controller.batches.own_tracks(BatchKey.file(library.items[episode - 1]).in_show(controller._key)).rules


def test_tracks_without_a_name_have_a_line_per_file_and_a_name_keeps_its_line(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    rows = name_rows(controller)
    assert [(r["text"], r["clickable"], r["file"]) for r in rows] == [
        ("01 · no name", True, path_of(library, 1)),
        ("02 · no name", True, path_of(library, 2)),
        ("03 · no name", True, path_of(library, 3)),
        ("Commentary · every file with this name", True, ""),
    ] + [(f"{n:02} · Commentary", True, path_of(library, n)) for n in range(4, 11)]
    assert rows[1]["label"] == "02 · no name Kept"


def test_a_chip_whose_tracks_all_lack_a_name_lists_every_file_and_each_can_be_clicked(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, _unnamed(library, 10), qtbot)
    rows = name_rows(controller)
    assert [r["file"] for r in rows] == [path_of(library, n) for n in range(1, 11)]
    assert all(r["clickable"] for r in rows)


def test_a_click_on_a_file_line_is_that_episode_own_choice_and_leaves_the_others_alone(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_file_track(COMMENTARY, path_of(library, 2))
    # The episode holds a drop of its own; the season, a name rule and the chip's own choice are untouched.
    own = file_rules(controller, library, 2)
    assert [(r.verdict.value, r.from_choice) for r in own] == [("drop", True)]
    # A choice on the chip, not a rule by name.
    assert (own[0].match.name, own[0].match.name_is_regex) == ("", False)
    assert controller.rules == []
    assert all(file_rules(controller, library, n) == [] for n in (1, 3, 4, 10))
    settle(controller, qtbot)
    assert states(controller) == ["kept", "dropped"] + ["kept"] * 8
    rows = name_rows(controller)
    assert [(r["dropped"], r["over"]) for r in rows[:3]] == [(False, ""), (True, "Own choice"), (False, "")]
    assert rows[1]["label"] == "02 · no name Dropped Own choice"
    assert controller.matrix["headers"][COMMENTARY]["state"] == "kept"
    # A second click gives the choice back to the season: the episode follows it again.
    controller.toggle_file_track(COMMENTARY, path_of(library, 2))
    assert file_rules(controller, library, 2) == []
    settle(controller, qtbot)
    assert states(controller) == ["kept"] * 10
    assert [r["over"] for r in name_rows(controller)] == [""] * 11


def test_an_episode_keeps_its_track_where_the_season_drops_the_chip_and_discard_takes_it_back(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    season = season_of(controller, library)
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    assert [r["dropped"] for r in name_rows(controller)[:3]] == [True, True, True]
    controller.toggle_file_track(COMMENTARY, path_of(library, 3))
    settle(controller, qtbot)
    assert [r.verdict.value for r in file_rules(controller, library, 3)] == ["keep"]
    assert states(controller) == ["dropped"] * 2 + ["kept"] + ["dropped"] * 7
    # Open on the episode alone, the same choice is the place's own, and Discard changes removes it.
    controller.select(controller.tree.index_of(path_of(library, 3)))
    settle(controller, qtbot)
    assert states(controller) == ["kept"]
    assert controller.can_discard
    controller.discard_changes()
    settle(controller, qtbot)
    assert states(controller) == ["dropped"]
    assert file_rules(controller, library, 3) == []
    controller.select(season)
    settle(controller, qtbot)
    assert states(controller) == ["dropped"] * 10


def test_a_click_on_nothing_changes_nothing(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_file_track(COMMENTARY, "no/such/file.mkv")
    controller.toggle_file_track(99, path_of(library, 1))
    assert all(file_rules(controller, library, n) == [] for n in range(1, 11))
    assert controller.rules == []


# The window: the chip, its expand button and the lines.


def _chip(root: QQuickItem) -> QQuickItem:
    return _visible(root, f"chip{COMMENTARY}")[0]


def _open_window(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot, place: str = "overview"
) -> QQuickItem:
    load()
    load.window.setHeight(1100)  # room for the lines under an opened chip
    controller.start()
    controller.model.set_library(library)
    controller.select(season_of(controller, library))
    settle(controller, qtbot)
    load.window.setProperty("place", place)
    load()
    return load.window.contentItem()


def test_opening_a_chip_does_not_make_it_wider_and_a_click_on_a_line_makes_the_file_choice(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _open_window(load, controller, library, qtbot)
    closed = _chip(root).width()
    button = _visible(_chip(root), "namesButton")[0]
    # The button ends the row, its own column, as far as it can be from the box that keeps or drops.
    box = _visible(_chip(root), "keepBox")[0]
    assert button.width() == SIZES["track_files_width"]
    assert button.mapToItem(_chip(root), QPointF(button.width(), 0)).x() <= closed
    assert box.mapToItem(button, QPointF(box.width(), 0)).x() < 0
    _click(load.window, button)
    load()
    assert _chip(root).width() == closed
    lines = _visible(root, "chipNameRow")
    assert len(lines) == 11
    assert all(line.width() <= closed for line in lines)
    _click(load.window, lines[1])
    settle(controller, qtbot)
    load()
    assert [r["dropped"] for r in name_rows(controller)[:3]] == [False, True, False]
    assert [r.verdict.value for r in file_rules(controller, library, 2)] == ["drop"]
    assert controller.rules == []
    assert _chip(root).width() == closed
    assert qt_warnings() == []


def test_the_expand_button_is_not_the_chip_keep_or_drop(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    root = _open_window(load, controller, library, qtbot)
    _click(load.window, _visible(_chip(root), "namesButton")[0])
    load()
    assert controller.matrix["headers"][COMMENTARY]["state"] == "kept"
    assert controller.rules == []


# Tracks: a cell of the strip, the toolbar and the D mark.


def _cell(root: QQuickItem, column: int, at: int) -> QQuickItem:
    """The cell of file `at` under the track row of `column`."""
    (line,) = (i for i in _visible(root, "trackLine") if i.property("index") == column)
    return next(c for c in _visible(line, "stripCell") if c.property("at") == at)


def test_a_click_on_a_cell_is_that_file_own_choice_and_a_second_takes_it_back(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _open_window(load, controller, library, qtbot, "tracks")
    assert controller.matrix["headers"][COMMENTARY]["id"] == COMMENTARY  # the rows stand in the files' order
    _click(load.window, _cell(root, COMMENTARY, 1))
    settle(controller, qtbot)
    load()
    assert [r.verdict.value for r in file_rules(controller, library, 2)] == ["drop"]
    assert controller.rules == []
    assert _cell(root, COMMENTARY, 1).property("mark") == "own_drop"
    # A track with a name is a file's own choice too, where the Overview row lists it by its name.
    _click(load.window, _cell(root, COMMENTARY, 4))
    settle(controller, qtbot)
    load()
    assert [r.verdict.value for r in file_rules(controller, library, 5)] == ["drop"]
    assert states(controller) == ["kept", "dropped", "kept", "kept", "dropped"] + ["kept"] * 5
    _click(load.window, _cell(root, COMMENTARY, 1))
    _click(load.window, _cell(root, COMMENTARY, 4))
    settle(controller, qtbot)
    load()
    assert file_rules(controller, library, 2) == file_rules(controller, library, 5) == []
    # A file without the track, and a paired file nobody adds, take no click.
    _click(load.window, _cell(root, 1, 6))  # Episode Seven has no Turkish audio
    _click(load.window, _cell(root, len(controller.matrix["headers"]) - 1, 0))
    settle(controller, qtbot)
    assert all(file_rules(controller, library, n) == [] for n in range(1, 11))
    assert controller.rules == []
    assert qt_warnings() == []


def test_the_pointer_over_a_cell_shows_what_it_means(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    root = _open_window(load, controller, library, qtbot, "tracks")
    controller.toggle_file_track(COMMENTARY, path_of(library, 5))
    settle(controller, qtbot)
    load()
    cell = _cell(root, COMMENTARY, 4)
    assert cell.property("mark") == "own_drop"
    centre = cell.mapToScene(QPointF(cell.width() / 2, cell.height() / 2)).toPoint()
    QTest.mouseMove(load.window, centre - QPoint(SIZES["strip_pitch"] * 2, 0))  # onto the strip, then the cell
    QTest.mouseMove(load.window, centre)
    (line,) = (i for i in _visible(root, "trackLine") if i.property("index") == COMMENTARY)
    shown = lambda: [t for t in line.findChildren(QObject, "cellTip") if t.property("visible")]  # noqa: E731
    qtbot.waitUntil(lambda: shown() != [])
    (tip,) = shown()
    assert tip.property("text") == controller.cell_tip(COMMENTARY, path_of(library, 5))
    assert tip.property("text").startswith("05 · Episode Five\n")
    assert tip.property("text").endswith("Click to follow its track again.")
    assert qt_warnings() == []


def test_the_toolbar_shares_a_line_and_the_help_comes_last(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load.window.setWidth(1920)
    root = _open_window(load, controller, library, qtbot, "tracks")
    items = [*_visible(root, "stripFiles"), *_visible(root, "writeImpliedFlags"), *_visible(root, "firstKeptTip")]
    centres = {round(i.mapToScene(QPointF(0, i.height() / 2)).y()) for i in items}
    assert len(items) == 3
    assert len(centres) == 1
    (write,) = _visible(root, "writeImpliedFlags")
    (tip,) = _visible(root, "firstKeptTip")
    assert tip.mapToScene(QPointF()).x() >= write.mapToScene(QPointF(write.width(), 0)).x()


def test_a_default_is_marked_d_like_forced_in_the_inspector_list(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_flag(1, "default")
    settle(controller, qtbot)
    changes = controller.inspector["changes"]
    assert [c["icon"] for c in changes if "Default" in str(c["text"])] == ["default"]


def test_over_a_whole_show_a_divider_names_each_season_before_its_first_file(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.select(season_of(controller, library).parent())
    settle(controller, qtbot)
    rows = name_rows(controller)
    dividers = [(n, r["text"]) for n, r in enumerate(rows) if r["divider"]]
    assert [text for _, text in dividers] == ["Season 1", "Season 2"] * 2  # the files without a name, then the name's
    # A divider is no line to click, and the file after it is the first of its season.
    assert not any(rows[n]["clickable"] for n, _ in dividers)
    assert [rows[n + 1]["text"].split(" · ")[0] for n, _ in dividers] == ["S01E01", "S02E01", "S01E04", "S02E04"]
