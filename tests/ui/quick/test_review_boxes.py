"""The tick boxes of Review, the flag lines under the implied-flags switch, and what the tab counts show."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.core.media import Episode
from showrunner.ui.quick.window import WindowController

from .conftest import neutral_library
from .test_choices import open_season, settle


@pytest.fixture
def library() -> Library:
    """Every commentary track already has the flag its name implies."""

    def flagged(item: Any) -> Any:
        if not isinstance(item.identity, Episode):
            return item
        tracks = tuple(
            replace(t, flags=replace(t.flags, commentary=True)) if t.name == "Commentary" else t
            for t in item.file.tracks
        )
        return replace(item, file=replace(item.file, tracks=tracks))

    base = neutral_library()
    return replace(base, items=tuple(flagged(i) for i in base.items))


def tabs(controller: WindowController) -> dict[str, int]:
    return {tab["key"]: tab["count"] for tab in controller.workspace_tabs}


def test_a_line_says_there_is_nothing_to_write_when_every_name_flag_is_set(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    open_season(controller, library, qtbot)
    assert not controller.implied_nothing  # the switch is off: nothing to explain
    controller.set_write_implied_flags(True)
    settle(controller, qtbot)
    assert controller.implied_nothing
    assert tabs(controller)["tracks"] == 0
    controller.set_write_implied_flags(False)
    settle(controller, qtbot)
    assert not controller.implied_nothing


def test_a_flag_change_counts_on_tracks_and_in_review_not_on_names(
    controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    # One episode's commentary lacks its flag again, so only that file has something to write.
    lacking = library.items[1]
    library = replace(
        library,
        items=tuple(
            replace(
                i,
                file=replace(
                    i.file,
                    tracks=tuple(
                        replace(t, flags=replace(t.flags, commentary=False)) if t.name == "Commentary" else t
                        for t in i.file.tracks
                    ),
                ),
            )
            if i is lacking
            else i
            for i in library.items
        ),
    )
    open_season(controller, library, qtbot)
    controller.set_write_implied_flags(True)
    settle(controller, qtbot)
    assert not controller.implied_nothing
    assert (tabs(controller)["tracks"], tabs(controller)["names"], tabs(controller)["review"]) == (1, 0, 1)
    row = next(r for r in controller.review["rows"] if r["count"])
    lines = [d["text"] for d in row["detail"] if d["text"]]
    assert lines == ["Commentary flag set on “Commentary”"]
