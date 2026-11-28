"""Subtitle files paired by hand from the Inspector: Unpair, Pair instead and Pair here change the library at once and
are kept with the workspace, so Refresh and the next start lay them over the scan's own pairing."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.ui.quick.window import WindowController

from .conftest import neutral_library
from .test_choices import settle
from .test_discard import _click, _visible
from .test_remove import _controller, open_folders, pick, row


@pytest.fixture
def controller(qapp: QApplication) -> Iterator[WindowController]:
    controller = _controller()
    yield controller
    controller.deleteLater()


@pytest.fixture
def season(make: Callable[..., Path], tmp_path: Path) -> Path:
    """Two episodes, each with its subtitle file by name, and one file that fits neither."""
    for relative in (
        "media/Show Name (2020)/Season 1/Show Name - S01E01.mkv",
        "media/Show Name (2020)/Season 1/Show Name - S01E01.tr.srt",
        "media/Show Name (2020)/Season 1/Show Name - S01E02.mkv",
        "media/Show Name (2020)/Season 1/Show Name - S01E02.tr.srt",
        "media/Show Name (2020)/Season 1/Bonus Notes.en.srt",
    ):
        make(relative)
    return tmp_path / "media" / "Show Name (2020)"


def owners(controller: WindowController) -> dict[str, str | None]:
    return {s.name: v.name if v else None for s, v in controller.model.library.owners().items()}


def first_episode(controller: WindowController, qtbot: QtBot, show: Path) -> str:
    pick(controller, qtbot, row(controller, show, "Show Name - S01E01.mkv"))
    return controller.focus_path


def test_a_pairing_by_hand_survives_refresh(controller: WindowController, season: Path, qtbot: QtBot) -> None:
    open_folders(controller, qtbot, season)
    video = first_episode(controller, qtbot, season)
    assert owners(controller)["Bonus Notes.en.srt"] is None
    controller.pair_subtitle(str(season / "Season 1" / "Bonus Notes.en.srt"), video)
    controller.unpair_subtitle(str(season / "Season 1" / "Show Name - S01E01.tr.srt"))
    expected = {
        "Bonus Notes.en.srt": "Show Name - S01E01.mkv",
        "Show Name - S01E01.tr.srt": None,
        "Show Name - S01E02.tr.srt": "Show Name - S01E02.mkv",
    }
    assert owners(controller) == expected
    # The open place follows: the Inspector lists the file now paired, and the plans hold it.
    assert [f["name"] for f in controller.inspector["pairing"]["paired"]] == ["Bonus Notes.en.srt"]
    assert [s.path.name for s in controller.workspace.items[0].subtitles] == ["Bonus Notes.en.srt"]
    controller.refresh_library()
    qtbot.waitUntil(lambda: not controller.busy)
    assert owners(controller) == expected


def test_a_pairing_by_hand_survives_a_restart(
    controller: WindowController, season: Path, qtbot: QtBot, qapp: QApplication
) -> None:
    open_folders(controller, qtbot, season)
    first_episode(controller, qtbot, season)
    controller.unpair_subtitle(str(season / "Season 1" / "Show Name - S01E01.tr.srt"))
    folder = season / "Season 1"
    controller.pair_subtitle(str(folder / "Show Name - S01E01.tr.srt"), str(folder / "Show Name - S01E02.mkv"))
    controller.workspace.save_batches()
    expected = owners(controller)
    assert expected["Show Name - S01E01.tr.srt"] == "Show Name - S01E02.mkv"
    again = _controller()
    try:
        open_folders(again, qtbot, season)
        assert owners(again) == expected
    finally:
        again.deleteLater()


def test_an_unpair_by_hand_stays_unpaired(controller: WindowController, season: Path, qtbot: QtBot) -> None:
    open_folders(controller, qtbot, season)
    first_episode(controller, qtbot, season)
    controller.unpair_subtitle(str(season / "Season 1" / "Show Name - S01E02.tr.srt"))
    controller.refresh_library()
    qtbot.waitUntil(lambda: not controller.busy)
    assert owners(controller)["Show Name - S01E02.tr.srt"] is None
    assert controller.model.library.item(season / "Season 1" / "Show Name - S01E02.mkv").subtitles == ()


def test_a_pairing_whose_file_is_gone_is_dropped(controller: WindowController, season: Path, qtbot: QtBot) -> None:
    open_folders(controller, qtbot, season)
    video = first_episode(controller, qtbot, season)
    bonus = season / "Season 1" / "Bonus Notes.en.srt"
    controller.pair_subtitle(str(bonus), video)
    assert bonus in controller.batches.pairings
    bonus.unlink()
    controller.refresh_library()
    qtbot.waitUntil(lambda: not controller.busy)
    assert bonus not in controller.batches.pairings
    assert "Bonus Notes.en.srt" not in owners(controller)


def test_a_click_on_pair_instead_reaches_the_library(
    load: Any, controller: WindowController, library: Library, qtbot: QtBot
) -> None:
    load()
    controller.model.set_library(library)
    seventh = library.items[6]
    controller.select(controller.tree.index_of(str(seventh.file.path)))
    settle(controller, qtbot)
    assert load() == []
    alternative = library.alternatives[0].subtitles[0]
    button = _visible(load.window.contentItem(), "pairing_instead_0")
    assert button.property("enabled")
    _click(load.window, button)
    qtbot.waitUntil(lambda: controller.model.library.item(seventh.file.path).subtitles == (alternative,))
    assert controller.model.library.alternatives == ()
    assert controller.batches.pairings[alternative.path] == seventh.file.path


def test_the_inspector_lists_the_files_of_a_doubt_and_the_unpaired_ones_near(controller: WindowController) -> None:
    library = neutral_library()
    seventh = library.items[6]
    controller.model.set_library(library)
    controller.select(controller.tree.index_of(str(seventh.file.path)))
    pairing = controller.inspector["pairing"]
    assert [f["name"] for f in pairing["paired"]] == [s.path.name for s in seventh.subtitles]
    assert [f["name"] for f in pairing["alternatives"]] == [library.alternatives[0].subtitles[0].path.name]
    assert pairing["unpaired"] == []
