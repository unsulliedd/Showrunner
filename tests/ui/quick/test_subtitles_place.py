"""The Subtitles place: its rows show the place's subtitle settings with where each value comes from, the row menu
follows the parent again or makes "as it is" the place's own value, and the file list names each file's work. Work no
engine can do is left out and said so, in the tab and in Review."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.dependencies.service import mkvpropedit_from, programs_from
from showrunner.app.jobs.stages import Stage, pipeline
from showrunner.app.library.library import Library
from showrunner.core.track import TrackKind
from showrunner.stages.subtitles import StepKind
from showrunner.stages.subtitles.work import StepWork
from showrunner.ui.quick.window import WindowController
from showrunner.ui.quick.workspace import Statuses

from .conftest import neutral_library, program_statuses
from .test_choices import open_season, settle

# Every kind of work but the wait for approval, as the engines of later versions will make them.
ENGINES = tuple(kind for kind in StepKind if kind is not StepKind.APPROVAL)


def never(work: StepWork, cancel: threading.Event | None) -> None:
    raise AssertionError("these tests plan subtitle work, they never run it")


def with_engines(statuses: Statuses) -> Sequence[Stage]:
    return pipeline(programs_from(statuses), mkvpropedit_from(statuses), runners=dict.fromkeys(ENGINES, never))


@pytest.fixture
def engines(qapp: QApplication) -> Iterator[WindowController]:
    """A window controller whose pipeline has an engine for every kind of work but approval."""
    controller = WindowController(statuses=program_statuses, make_pipeline=with_engines)
    yield controller
    controller.deleteLater()


def row(controller: WindowController, key: str) -> dict[str, Any]:
    return next(r for r in controller.subtitles["rows"] if r["key"] == key)


def add_language(controller: WindowController, tag: str) -> None:
    controller.pick_wanted_language()
    controller.language_picker.set_typed(tag)
    controller.language_picker.apply()


def test_a_show_s_settings_reach_its_season_marked_and_the_season_overrides_them(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    season = controller.tree.index_of(str(library.items[2].file.path)).parent()
    controller.select(season.parent())
    controller.set_subtitle_choice("sync", "alass")
    add_language(controller, "de")
    settle(controller, qtbot)
    assert controller.subtitles["title"] == "Subtitles in this show"
    assert controller.subtitles["follow"] == ""  # the show has nothing above it to follow
    controller.select(season)
    settle(controller, qtbot)
    assert controller.subtitles["title"] == "Subtitles in this season"
    assert (row(controller, "sync")["value"], row(controller, "sync")["received"]) == ("alass", True)
    assert controller.field_marks["subtitles.sync"] == {"from": "From the show", "over": ""}
    (german,) = row(controller, "wanted")["items"]
    assert (german["label"], german["off"], german["mark"]["from"]) == ("DEU", False, "From the show")
    # Every episode gets a German subtitle, translated from its reference.
    assert controller.workspace_tabs[2]["key"] == "subtitles"
    assert controller.workspace_tabs[2]["count"] > 0
    plan = controller.subtitles["files"][0]["plan"]
    assert [(p["code"], p["steps"]) for p in plan] == [("DEU", "translate")]

    # The season says no to German for itself, and picks its own engine.
    controller.toggle_subtitle_item("wanted", "de")
    controller.set_subtitle_choice("sync", "ffsubsync")
    settle(controller, qtbot)
    (german,) = row(controller, "wanted")["items"]
    assert (german["off"], german["mark"]["over"]) == (True, "Overrides the show")
    assert controller.field_marks["subtitles.sync"] == {"from": "", "over": "Overrides the show"}
    assert controller.subtitles["files"][0]["plan"] == []
    assert controller.subtitles["follow"] == "Follow the show again"

    # The row menu: follow the show again, or "as it is" as the season's own value.
    controller.follow_subtitles("sync")
    assert (row(controller, "sync")["value"], row(controller, "sync")["own"]) == ("alass", False)
    controller.subtitles_as_it_is("sync")
    assert (row(controller, "sync")["value"], row(controller, "sync")["own"]) == ("", True)
    controller.toggle_subtitle_item("wanted", "de")
    assert row(controller, "wanted")["items"][0]["off"] is False
    controller.subtitles_as_it_is("wanted")
    assert row(controller, "wanted")["items"][0]["off"] is True
    # Discard changes takes every own value away.
    controller.discard_changes()
    settle(controller, qtbot)
    assert row(controller, "sync")["value"] == "alass"
    assert row(controller, "wanted")["items"][0]["off"] is False


def test_review_shows_the_subtitles_group_with_counts_that_add_up(
    engines: WindowController, library: Library, qtbot: QtBot
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    add_language(controller, "de")
    settle(controller, qtbot)
    shown = controller.review
    group = next(g for g in shown["groups"] if g["key"] == "subtitles")
    # Ten translations, and the ten new files only they ask for.
    assert [(line["label"], line["count"]) for line in group["lines"]] == [
        ("Finished subtitles", 10),
        ("New files only subtitles ask for", 10),
    ]
    assert group["problems"] == []
    assert "Subtitles" not in shown["stays"]
    assert shown["count"] == sum(line["count"] for g in shown["groups"] for line in g["lines"])
    first = shown["rows"][0]
    assert [m["key"] for m in first["marks"]] == ["tracks", "names", "subtitles"]
    assert next(m for m in first["marks"] if m["key"] == "subtitles")["on"]


def test_work_no_engine_can_do_is_left_out_and_said_so(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    tracks_before = controller.workspace_tabs[1]["count"]
    states_before = [r["state"] for r in controller.review["rows"]]
    add_language(controller, "de")
    controller.set_subtitle_choice("sync", "alass")
    settle(controller, qtbot)
    # This version has no engine, so nothing is planned for subtitles and the track choices plan as before.
    assert controller.workspace_tabs[2]["count"] == 0
    assert controller.workspace_tabs[1]["count"] == tracks_before
    assert row(controller, "wanted")["note"] == "Translate is not available in this version yet"
    assert row(controller, "sync")["note"] == ""  # no paired file is added, so nothing asks for a sync
    plan = controller.subtitles["files"][0]["plan"]
    assert [(p["code"], p["cannot"]) for p in plan] == [("DEU", "Translate is not available in this version yet")]
    shown = controller.review
    group = next(g for g in shown["groups"] if g["key"] == "subtitles")
    assert group["lines"] == []
    assert group["problems"] == [
        "Translate is not available in this version yet, so 10 subtitles are left out. The rest of each file goes on"
        " without them."
    ]
    # Left out is not a look: the files go on with their other changes.
    assert [r["state"] for r in shown["rows"]] == states_before


def test_a_file_that_cannot_get_its_subtitle_needs_a_look_and_says_why(
    controller: WindowController, qtbot: QtBot
) -> None:
    sample = neutral_library()
    first = sample.items[0]
    bare = replace(first.file, tracks=tuple(t for t in first.file.tracks if t.kind is not TrackKind.SUBTITLE))
    library = replace(sample, items=(replace(first, file=bare), *sample.items[1:]))
    open_season(controller, library, qtbot, episode=0)
    add_language(controller, "de")
    settle(controller, qtbot)
    plan = controller.subtitles["files"][0]["plan"]
    assert [(p["code"], p["cannot"]) for p in plan] == [("DEU", "no subtitle to translate from")]
    row = controller.review["rows"][0]
    assert (row["state"], row["warning"]) == ("look", "DEU subtitle cannot be made: no subtitle to translate from")
    assert controller.review["rows"][1]["state"] == "in"


def test_the_place_draws_without_warnings(
    load: Any, controller: WindowController, library: Library, qt_warnings: Any, qtbot: QtBot
) -> None:
    load()
    open_season(controller, library, qtbot)
    controller.set_subtitle_choice("approval", "every")
    add_language(controller, "de")
    settle(controller, qtbot)
    load.window.setProperty("place", "subtitles")
    assert load() == []
    controller.set_subtitle_choice("sync", "alass")
    assert load() == []
    load.window.setProperty("place", "review")
    assert load() == []
    assert qt_warnings() == []
