"""Refresh in the library's header and in a row's menu: the open folders are read again, so files deleted on disk drop
out and new ones come in, while what was taken out of the list stays out and the choices of each place stay."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.settings.app_settings import load_settings
from showrunner.ui.quick.window import WindowController

from .test_discard import _click, _visible
from .test_remove import _controller, listed, open_folders, pick, row


@pytest.fixture
def controller(qapp: QApplication) -> Iterator[WindowController]:
    controller = _controller()
    yield controller
    controller.deleteLater()


@pytest.fixture
def folders(make: Callable[..., Path], tmp_path: Path) -> tuple[Path, Path]:
    """Show Name (2020) with two seasons and Another Show (2018) with one, in two folders."""
    for relative in (
        "media/Show Name (2020)/Season 1/Show Name - S01E01.mkv",
        "media/Show Name (2020)/Season 1/Show Name - S01E02.mkv",
        "media/Show Name (2020)/Season 2/Show Name - S02E01.mkv",
        "media/Another Show (2018)/Season 1/Another Show - S01E01.mkv",
    ):
        make(relative)
    media = tmp_path / "media"
    return media / "Show Name (2020)", media / "Another Show (2018)"


def refreshed(controller: WindowController, qtbot: QtBot, action: Callable[[], None]) -> None:
    action()
    qtbot.waitUntil(lambda: not controller.busy)


def test_refresh_drops_a_deleted_file_and_lists_a_new_one_once(
    controller: WindowController, folders: tuple[Path, Path], make: Callable[..., Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, show, "Show Name - S02E01.mkv", up=1))
    season = controller.selected
    (show / "Season 1" / "Show Name - S01E02.mkv").unlink()
    make("media/Show Name (2020)/Season 2/Show Name - S02E02.mkv")
    refreshed(controller, qtbot, controller.refresh_library)
    assert sorted(listed(controller)) == [
        "Another Show - S01E01.mkv",
        "Show Name - S01E01.mkv",
        "Show Name - S02E01.mkv",
        "Show Name - S02E02.mkv",
    ]
    assert controller.model.library.roots == (show, other)
    assert controller.selected == season


def test_refresh_keeps_a_removed_video_out_and_a_place_excluded(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, show, "Show Name - S02E01.mkv"))
    controller.place_action("remove")
    pick(controller, qtbot, row(controller, other, "Another Show - S01E01.mkv", up=2))
    controller.exclude_place(True)
    assert controller.place_excluded
    refreshed(controller, qtbot, controller.refresh_library)
    assert "Show Name - S02E01.mkv" not in listed(controller)
    pick(controller, qtbot, row(controller, other, "Another Show - S01E01.mkv", up=2))
    assert controller.place_excluded


def test_a_rows_menu_refreshes_the_folder_it_comes_from(
    controller: WindowController, folders: tuple[Path, Path], make: Callable[..., Path], qtbot: QtBot
) -> None:
    _, other = folders
    open_folders(controller, qtbot, *folders)
    pick(controller, qtbot, row(controller, other, "Another Show - S01E01.mkv", up=1))
    (action,) = (a for a in controller.place_actions if a["key"] == "refresh")
    assert action["enabled"]
    assert "Another Show (2018)" in action["tip"]
    make("media/Another Show (2018)/Season 1/Another Show - S01E02.mkv")
    make("media/Show Name (2020)/Season 3/Show Name - S03E01.mkv")  # another folder: not read now
    refreshed(controller, qtbot, lambda: controller.place_action("refresh"))
    assert "Another Show - S01E02.mkv" in listed(controller)
    assert "Show Name - S03E01.mkv" not in listed(controller)


def test_a_folder_deleted_on_disk_is_closed_by_refresh(
    controller: WindowController, folders: tuple[Path, Path], qtbot: QtBot
) -> None:
    show, other = folders
    open_folders(controller, qtbot, *folders)
    for path in sorted(other.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    other.rmdir()
    refreshed(controller, qtbot, controller.refresh_library)
    assert controller.model.library.roots == (show,)
    assert all(name.startswith("Show Name") for name in listed(controller))
    assert load_settings().value.last_folders == [str(show)]


def test_the_header_button_refreshes_the_library(
    controller: WindowController, folders: tuple[Path, Path], make: Callable[..., Path], qtbot: QtBot, load: Any
) -> None:
    open_folders(controller, qtbot, *folders)
    load()
    make("media/Show Name (2020)/Season 2/Show Name - S02E02.mkv")
    button = _visible(load.window.contentItem(), "refreshLibrary")
    assert button.property("enabled")
    _click(load.window, button)
    qtbot.waitUntil(lambda: "Show Name - S02E02.mkv" in listed(controller))
    assert not [w for w in load() if "StatusBar" in w or "LibraryPanel" in w]


def test_a_refresh_that_ends_after_a_job_started_leaves_the_library_as_it_was(
    controller: WindowController,
    folders: tuple[Path, Path],
    make: Callable[..., Path],
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    show, _ = folders
    open_folders(controller, qtbot, *folders)
    before = listed(controller)
    (show / "Season 1" / "Show Name - S01E02.mkv").unlink()
    make("media/Show Name (2020)/Season 2/Show Name - S02E02.mkv")
    controller.refresh_library()
    # The load ends on the window's thread, so a job that starts now starts before it is taken in.
    monkeypatch.setattr(controller.run, "locked_paths", lambda: {show / "Season 1" / "Show Name - S01E01.mkv"})
    qtbot.waitUntil(lambda: not controller.busy)
    assert listed(controller) == before
    assert "a job started" in controller.job_text
