"""Extras: videos of a show that belong to no season, listed under the show after its seasons, as places of their own
inside the show: its choices, Exclude and Discard reach them, and they hold their own."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QModelIndex
from pytestqt.qtbot import QtBot

from showrunner.app.batches.batch import BatchKey
from showrunner.app.library.library import Library
from showrunner.core.media import Extra, MediaItem
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.model import Kind
from showrunner.ui.quick.facts import heading
from showrunner.ui.quick.library import EXCLUDED, KIND, LABEL
from showrunner.ui.quick.window import WindowController
from showrunner.ui.sheet.format import count_parts, item_title

from .test_choices import COMMENTARY, settle


def with_extras(library: Library) -> Library:
    """The sample library with two extras of Show Name (2020), the first episode's tracks in each."""
    base = library.items[0]
    extras = tuple(
        MediaItem(
            Extra("Show Name", title, 2020),
            replace(base.file, path=Path("Show Name (2020)") / "Extras" / f"{title}.mkv"),
        )
        for title in ("Making Of", "Bloopers")
    )
    return replace(library, items=(*library.items, *extras))


def row_of(controller: WindowController, kind: Kind, label: str) -> QModelIndex:
    tree = controller.tree
    return next(
        index for index in tree._indexes(QModelIndex()) if index.data(KIND) == kind.value and index.data(LABEL) == label
    )


def open_extras(controller: WindowController, library: Library, qtbot: QtBot) -> Library:
    library = with_extras(library)
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    controller.model.set_library(library)
    return library


def test_extras_are_listed_under_their_show_after_its_seasons(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_extras(controller, library, qtbot)
    show = row_of(controller, Kind.SHOW, "Show Name (2020)")
    kinds = [controller.tree.index(row, 0, show).data(KIND) for row in range(controller.tree.rowCount(show))]
    assert kinds == ["season", "season", "extras"]
    group = controller.tree.index(2, 0, show)
    assert group.data(LABEL) == tr("library.extras")
    assert [controller.tree.index(row, 0, group).data(LABEL) for row in range(2)] == ["Bloopers", "Making Of"]
    assert controller.tree.index(0, 0, group).data(KIND) == "extra"
    assert show.siblingAtColumn(0).data(LABEL) == "Show Name (2020)"


def test_the_extras_group_and_one_extra_open_as_places(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_extras(controller, library, qtbot)
    group = row_of(controller, Kind.EXTRAS, tr("library.extras"))
    controller.select(group)
    settle(controller, qtbot)
    assert controller.batch_kind == "extras"
    assert controller.batch["title"] == tr("library.extras")
    assert controller.batch["over"] == "Show Name (2020)"
    controller.select(row_of(controller, Kind.EXTRA, "Making Of"))
    settle(controller, qtbot)
    assert controller.batch_kind == "extra"
    assert controller.batch["title"] == "Making Of"
    assert controller.batch["over"] == f"Show Name (2020) · {tr('library.extras')}"


def test_a_choice_on_the_show_reaches_an_extra_and_it_holds_its_own(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_extras(controller, library, qtbot)
    controller.select(row_of(controller, Kind.SHOW, "Show Name (2020)"))
    settle(controller, qtbot)
    controller.toggle_keep(COMMENTARY)
    controller.select(row_of(controller, Kind.EXTRA, "Making Of"))
    settle(controller, qtbot)
    assert not controller.can_discard  # it follows the show
    controller.toggle_keep(COMMENTARY)  # its own choice, over the show's
    assert controller.can_discard
    controller.select(row_of(controller, Kind.EXTRA, "Bloopers"))
    settle(controller, qtbot)
    assert not controller.can_discard


def test_excluding_the_extras_reaches_each_one_and_the_show_reaches_them_too(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_extras(controller, library, qtbot)
    controller.select(row_of(controller, Kind.EXTRAS, tr("library.extras")))
    settle(controller, qtbot)
    controller.exclude_place(True)
    assert controller.place_excluded
    assert row_of(controller, Kind.EXTRA, "Making Of").data(EXCLUDED)
    assert row_of(controller, Kind.EXTRA, "Bloopers").data(EXCLUDED)
    assert not row_of(controller, Kind.SEASON, tr("library.season", number=1)).data(EXCLUDED)
    controller.select(row_of(controller, Kind.EXTRA, "Making Of"))
    settle(controller, qtbot)
    controller.exclude_place(False)  # included again on its own, inside the excluded group
    assert not row_of(controller, Kind.EXTRA, "Making Of").data(EXCLUDED)
    assert row_of(controller, Kind.EXTRA, "Bloopers").data(EXCLUDED)
    controller.select(row_of(controller, Kind.SHOW, "Show Name (2020)"))
    controller.exclude_place(True)
    assert row_of(controller, Kind.EXTRA, "Bloopers").data(EXCLUDED)
    assert row_of(controller, Kind.EXTRAS, tr("library.extras")).data(EXCLUDED)


def test_titles_counts_and_facts_name_extras(library: Library) -> None:
    library = with_extras(library)
    items = [i for i in library.items if getattr(i.identity, "show", "") == "Show Name"]
    extra = items[-1]
    assert item_title(extra) == "Show Name · Bloopers"
    parts = [text for text, _ in count_parts(library.counts([i.file.path for i in items]))]
    assert parts[1] == "1 show, 18 episodes, 2 extras"
    show = heading(BatchKey.of(extra, whole_show=True), items)
    dot = f" {tr('status.separator')} "
    assert show.facts.startswith(dot.join(("2 seasons", "18 episodes", "2 extras")))
    assert heading(BatchKey.of(extra), items[-2:]).facts.startswith("2 extras")
    one = heading(BatchKey.file(extra), [extra])
    assert (one.over, one.title) == (f"Show Name (2020) · {tr('library.extras')}", "Bloopers")
