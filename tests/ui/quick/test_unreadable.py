"""A file whose tracks could not be read says why on Overview, in the Inspector and in Review's Needs a look; one
not read yet says so without a problem."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.stages.scan import ProbeFailure
from showrunner.ui.quick.window import WindowController

from .test_choices import settle

REASON = "Not a Matroska file"
TEXT = f"Could not be read: {REASON}"


@pytest.fixture
def season(controller: WindowController, library: Library, qtbot: QtBot) -> Library:
    """The sample library with Episode Three unread: no tracks, and the library's failure for it."""
    third = library.items[2]
    unread = replace(third, file=replace(third.file, tracks=()))
    failed = replace(
        library,
        items=(*library.items[:2], unread, *library.items[3:]),
        failures=(ProbeFailure(third.file.path, REASON),),
    )
    controller.start()
    controller.model.set_library(failed)
    controller.select(controller.tree.index_of(str(third.file.path)).parent())
    settle(controller, qtbot)
    return failed


def test_overview_names_the_read_problem_in_the_row(controller: WindowController, season: Library) -> None:
    rows = controller.overview["rows"]
    unread, other = rows[2], rows[0]
    assert (unread["warning"], unread["changes_text"]) == (TEXT, "Not read")
    assert (other["warning"], other["changes_text"]) == ("", "No changes")


def test_overview_counts_the_unread_file_neither_as_having_nor_as_lacking_a_track(
    controller: WindowController, season: Library
) -> None:
    chips = [c for group in controller.overview["groups"] for c in group["chips"]]
    # Episode Three has no tracks to show, which says nothing about them: only Episode Seven lacks Turkish audio.
    assert [c["count"] for c in chips][:2] == ["", "missing in 1 file"]
    assert controller.track_missing(1) == "Missing in 07"
    assert all("03" not in controller.track_missing(i) for i in range(len(chips)))


def test_the_inspector_gives_the_read_problem(controller: WindowController, season: Library) -> None:
    controller.focus_file(str(season.items[2].file.path))
    assert controller.inspector["unread"] == TEXT
    controller.focus_file(str(season.items[0].file.path))
    assert controller.inspector["unread"] == ""


def test_review_puts_the_file_under_needs_a_look_with_the_reason(
    controller: WindowController, season: Library, qtbot: QtBot
) -> None:
    controller.show_place("review")
    review = controller.review
    (look,) = (f for f in review["filters"] if f["key"] == "look")
    assert look["count"] == 1
    row = review["rows"][2]
    assert (row["state"], row["warning"], row["summary"]) == ("look", TEXT, "Not read")
    assert [r["state"] for r in review["rows"]].count("look") == 1


def test_a_file_a_cancelled_read_did_not_reach_says_not_read_without_a_problem(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    third = library.items[2]
    unread = replace(third, file=replace(third.file, tracks=()))
    controller.start()
    controller.model.set_library(replace(library, items=(*library.items[:2], unread, *library.items[3:])))
    controller.select(controller.tree.index_of(str(third.file.path)).parent())
    settle(controller, qtbot)
    row = controller.overview["rows"][2]
    assert (row["warning"], row["changes_text"]) == ("", "Not read")
    chips = [c for group in controller.overview["groups"] for c in group["chips"]]
    assert [c["count"] for c in chips][:2] == ["", "missing in 1 file"]  # Episode Seven only, as for a failed file
    controller.focus_file(str(third.file.path))
    assert controller.inspector["unread"] == "Not read"
    controller.show_place("review")
    row = controller.review["rows"][2]
    assert (row["state"], row["summary"]) == ("in", "Not read")
