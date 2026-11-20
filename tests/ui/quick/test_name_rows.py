"""The names under an opened chip: where a chip groups tracks with different names, each name keeps or drops its own
tracks, as a rule by name in the place that is open."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.core.media import Episode
from showrunner.ui.quick.window import WindowController

from .conftest import cells, neutral_library
from .test_choices import COMMENTARY, ENGLISH, TURKISH, open_season, rules, settle

DIRECTOR = "Commentary with the director"
CAST = "Commentary with the cast"


@pytest.fixture
def library() -> Library:
    """The sample library with the commentary of episodes one to three named for the director, the others for the
    cast: one chip, two names."""
    base = neutral_library()

    def rename(item: Any) -> Any:
        if not isinstance(item.identity, Episode):
            return item
        name = DIRECTOR if item.identity.episode <= 3 else CAST
        tracks = tuple(replace(t, name=name) if t.name == "Commentary" else t for t in item.file.tracks)
        return replace(item, file=replace(item.file, tracks=tracks))

    return replace(base, items=tuple(rename(i) for i in base.items))


def states(controller: WindowController, column: int = COMMENTARY) -> list[str]:
    return [str(row[column]["state"]) for row in cells(controller)]


def name_rows(controller: WindowController, column: int = COMMENTARY) -> list[dict[str, Any]]:
    return list(controller.track_name_rows(column))


def season_of(controller: WindowController, library: Library) -> Any:
    return controller.tree.index_of(str(library.items[2].file.path)).parent()


def test_a_chip_with_several_names_lists_each_name_with_the_files_that_use_it(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    rows = name_rows(controller)
    assert [(r["text"], r["clickable"], r["dropped"]) for r in rows] == [
        (f"01, 02, 03 · {DIRECTOR}", True, False),
        (f"04, 05, 06, 07, 08, 09, 10 · {CAST}", True, False),
    ]
    assert rows[0]["label"] == f"01, 02, 03 · {DIRECTOR} Kept"
    # A chip whose tracks carry one name keeps its line per file, which no click acts on.
    plain = name_rows(controller, ENGLISH)
    assert len(plain) == 10
    assert not any(r["clickable"] for r in plain)
    assert plain[0]["text"] == "01 · English"
    # Neither does a click on something that is no name of the chip.
    controller.toggle_name(ENGLISH, "English")
    controller.toggle_name(COMMENTARY, "No such name")
    assert controller.rules == []


def test_a_chip_told_apart_by_name_has_one_name_and_nothing_to_click(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    first = library.items[0]
    twin = replace(first.file.tracks[1], id=20, name="Director")  # a second English track beside English
    items = (replace(first, file=replace(first.file, tracks=(*first.file.tracks, twin))), *library.items[1:])
    open_season(controller, replace(library, items=items), qtbot)
    english = [h for h in controller.matrix["headers"] if h["code"] == "ENG" and h["title"] == "Dolby Digital Plus 5.1"]
    assert len(english) == 2  # told apart by name: a chip each
    for header in english:
        assert not any(r["clickable"] for r in name_rows(controller, int(header["id"])))
        controller.toggle_name(int(header["id"]), "English")
        controller.toggle_name(int(header["id"]), "Director")
    assert controller.rules == []


def test_a_click_on_a_name_drops_its_tracks_alone_and_a_second_click_gives_them_back(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_name(COMMENTARY, DIRECTOR)
    assert rules(controller) == [f"Drop audio in ENG Dolby Digital 2.0 flagged commentary named {DIRECTOR}"]
    rule = controller.rules[0]
    assert (rule["from_choice"], rule["source"], rule["inherited"]) == (True, "from a name", False)
    rows = name_rows(controller)
    assert [r["dropped"] for r in rows] == [True, False]
    assert "Dropped" in str(rows[0]["label"])
    settle(controller, qtbot)
    assert states(controller) == ["dropped"] * 3 + ["kept"] * 7
    # The chip's own choice is not touched: it still reads kept, and its click is the chip's.
    header = controller.matrix["headers"][COMMENTARY]
    assert header["state"] == "kept"
    assert (controller.change_text, controller._key is not None) == ("3 changes in 3 files", True)
    controller.toggle_name(COMMENTARY, DIRECTOR)
    assert controller.rules == []
    settle(controller, qtbot)
    assert states(controller) == ["kept"] * 10


def test_a_name_is_kept_under_a_dropped_chip_and_the_chip_s_other_names_stay_dropped(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_keep(COMMENTARY)
    assert [r["dropped"] for r in name_rows(controller)] == [True, True]
    controller.toggle_name(COMMENTARY, CAST)
    # The name's rule leads the chip's.
    assert rules(controller) == [
        f"Keep audio in ENG Dolby Digital 2.0 flagged commentary named {CAST}",
        "Drop audio in ENG Dolby Digital 2.0 flagged commentary",
    ]
    settle(controller, qtbot)
    assert states(controller) == ["dropped"] * 3 + ["kept"] * 7
    # Tracks kept on purpose by a name are not tracks the plan holds back: the chip says nothing of them.
    header = controller.matrix["headers"][COMMENTARY]
    assert (header["state"], header["count"]) == ("dropped", "")
    assert controller.track_held(COMMENTARY) == ""
    # Next click drops it, the one after follows the chip again.
    controller.toggle_name(COMMENTARY, CAST)
    assert [r["verdict"] for r in _verdicts(controller)] == ["drop", "drop"]
    controller.toggle_name(COMMENTARY, CAST)
    assert rules(controller) == ["Drop audio in ENG Dolby Digital 2.0 flagged commentary"]
    settle(controller, qtbot)
    assert states(controller) == ["dropped"] * 10


def _verdicts(controller: WindowController) -> list[dict[str, str]]:
    assert controller._key is not None
    found = controller.batches.own_tracks(controller._key).rules
    return [{"verdict": r.verdict.value} for r in found]


def test_every_name_dropped_shows_the_chip_dropped_but_its_own_click_cannot_undo_the_names(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_name(COMMENTARY, DIRECTOR)
    controller.toggle_name(COMMENTARY, CAST)
    settle(controller, qtbot)
    assert controller.matrix["headers"][COMMENTARY]["state"] == "dropped"
    # The chip's click writes its own keep behind the names, which still decide first.
    controller.toggle_keep(COMMENTARY)
    settle(controller, qtbot)
    assert states(controller) == ["dropped"] * 10


def test_the_rule_by_name_is_in_the_rules_panel_and_pausing_it_gives_the_name_back_to_the_chip(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_name(COMMENTARY, DIRECTOR)
    controller.pause_rule(0, True)
    assert [r["dropped"] for r in name_rows(controller)] == [False, False]
    controller.toggle_name(COMMENTARY, DIRECTOR)  # the paused rule is switched on again, in its place
    assert [(r["enabled"], r["source"]) for r in controller.rules] == [(True, "from a name")]
    assert [r["dropped"] for r in name_rows(controller)] == [True, False]
    controller.remove_rule(0)  # a rule by name goes by clicking its name, as a chip's does
    assert len(controller.rules) == 1


def test_a_show_s_name_reaches_its_season_marked_and_the_season_can_override_it_and_discard_it(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    season = season_of(controller, library)
    controller.select(season.parent())
    controller.toggle_name(COMMENTARY, DIRECTOR)
    assert [r["from"] for r in name_rows(controller)] == ["", ""]
    controller.select(season)
    settle(controller, qtbot)
    rows = name_rows(controller)
    assert [(r["dropped"], r["from"]) for r in rows] == [(True, "From the show"), (False, "")]
    assert [(r["inherited"], r["from"]) for r in controller.rules] == [(True, "From the show")]
    assert controller.rules[0]["source"] == "from a name"
    assert states(controller) == ["dropped"] * 3 + ["kept"] * 7
    # Kept here: the season's own rule hides the show's, and the row says what it overrides.
    controller.toggle_name(COMMENTARY, DIRECTOR)
    settle(controller, qtbot)
    assert [(r["inherited"], r["enabled"]) for r in controller.rules] == [(False, True)]
    assert [r["dropped"] for r in name_rows(controller)] == [False, False]
    assert states(controller) == ["kept"] * 10
    # Discard changes takes it, and the season follows the show again.
    assert controller.can_discard
    controller.discard_changes()
    settle(controller, qtbot)
    assert [(r["dropped"], r["from"]) for r in name_rows(controller)] == [(True, "From the show"), (False, "")]
    assert states(controller) == ["dropped"] * 3 + ["kept"] * 7
    # The show's own choice is still there.
    controller.select(season.parent())
    assert [r["dropped"] for r in name_rows(controller)] == [True, False]


def test_a_season_that_chose_the_chip_decides_before_the_show_s_name_rule(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    season = season_of(controller, library)
    controller.select(season.parent())
    controller.toggle_name(COMMENTARY, DIRECTOR)
    controller.select(season)
    settle(controller, qtbot)
    controller.toggle_flag(COMMENTARY, "default")  # this season keeps the chip, with the star
    settle(controller, qtbot)
    assert [r["dropped"] for r in name_rows(controller)] == [False, False]
    assert states(controller) == ["kept"] * 10


def test_a_name_rule_changes_no_flag_of_the_chip(controller: WindowController, library: Library, qtbot: QtBot) -> None:
    open_season(controller, library, qtbot)
    controller.toggle_flag(ENGLISH, "default")
    controller.toggle_flag(TURKISH, "default")
    controller.toggle_name(COMMENTARY, DIRECTOR)
    header = controller.matrix["headers"][ENGLISH]
    assert (header["default"], controller.matrix["headers"][TURKISH]["default"]) == (True, True)
    assert controller.rules[0]["source"] == "from a name"  # the name's rule leads the stars' rules
    assert controller._key is not None
    rule = controller.batches.own_tracks(controller._key).rules[0]
    assert (rule.default.value, rule.forced.value) == ("leave", "leave")
    settle(controller, qtbot)
    # The stars stay where they were in every file; only the commentary of the first three files is dropped.
    assert [row[ENGLISH]["default"] for row in cells(controller)] == [True] * 10
    assert states(controller) == ["dropped"] * 3 + ["kept"] * 7


# The window: the list is drawn from these rows and answers the pointer and the keyboard.


def _items(root: QQuickItem, name: str) -> list[QQuickItem]:
    found = [root] if root.objectName() == name else []
    for child in root.childItems():
        found += _items(child, name)
    return found


def _visible(root: QQuickItem, name: str) -> list[QQuickItem]:
    return [i for i in _items(root, name) if i.isVisible()]


def _click(window: Any, item: QQuickItem) -> None:
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def test_the_names_are_lines_of_the_open_chip_that_a_click_or_the_keyboard_acts_on(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    controller.start()
    controller.model.set_library(library)
    controller.select(season_of(controller, library))
    settle(controller, qtbot)
    load()
    root = load.window.contentItem()
    chip = _visible(root, f"chip{COMMENTARY}")[0]
    _click(load.window, _visible(chip, "namesButton")[0])
    load()
    lines = _visible(root, "chipNameRow")
    assert len(lines) == 2
    # A click drops the name: the line turns to the dropped look and a rule exists.
    _click(load.window, lines[0])
    settle(controller, qtbot)
    load()
    assert [r["dropped"] for r in name_rows(controller)] == [True, False]
    assert [r["source"] for r in controller.rules] == ["from a name"]
    # The list is one tab stop: Down moves to the next name, Space acts on it.
    (rows,) = _visible(root, "chipNameRows")
    assert rows.property("activeFocusOnTab") is True
    rows.forceActiveFocus()
    QTest.keyClick(load.window, Qt.Key.Key_Down)
    QTest.keyClick(load.window, Qt.Key.Key_Space)
    settle(controller, qtbot)
    load()
    assert [r["dropped"] for r in name_rows(controller)] == [True, True]
    assert rows.property("currentIndex") == 1
    # Another click goes back to the chip; the chip itself was never clicked.
    _click(load.window, _visible(root, "chipNameRow")[0])
    _click(load.window, _visible(root, "chipNameRow")[1])
    settle(controller, qtbot)
    assert controller.rules == []
    assert qt_warnings() == []
