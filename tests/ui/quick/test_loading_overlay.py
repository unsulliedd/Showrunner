"""The loading overlay: the workspace is covered and blocked while files of the open place are read, and only then."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.library.loader import LibraryLoader
from showrunner.app.settings.app_settings import load_settings, save_settings
from showrunner.core.media import MediaFile
from showrunner.core.track import Track, TrackKind
from showrunner.tools.probe import Programs
from showrunner.tools.process import ProcessCancelledError
from showrunner.ui.quick.window import WindowController

from .conftest import program_statuses


class Held:
    """Reads at once, except the files named in `held`, which wait until they are let go or the read is cancelled."""

    def __init__(self) -> None:
        self.held: set[str] = set()
        self.stop = threading.Event()

    def __call__(self, path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        while path.name in self.held and not self.stop.is_set():
            if cancel is not None and cancel.is_set():
                raise ProcessCancelledError("cancelled", ())
            time.sleep(0.005)
        return MediaFile(path, "Matroska", tracks=(Track(0, TrackKind.VIDEO, "V_MPEG4/ISO/AVC"),))


@pytest.fixture
def read() -> Iterator[Held]:
    read = Held()
    yield read
    read.stop.set()  # no pool thread is left waiting after the test


@pytest.fixture
def loader(qapp: QApplication, read: Held) -> LibraryLoader:
    return LibraryLoader(programs=Programs(Path("mkvmerge")), read=read)


@pytest.fixture
def controller(loader: LibraryLoader, opened: list[str]) -> Iterator[WindowController]:
    controller = WindowController(statuses=program_statuses, loader=loader, get_program=opened.append)
    yield controller
    controller.deleteLater()


@pytest.fixture
def folders(make: Callable[..., Path], tmp_path: Path) -> dict[str, Path]:
    """Alpha with three episodes, and `more`, which holds a fourth Alpha episode and the first one of Beta."""
    for number in range(1, 4):
        make(f"Alpha/Alpha S01E0{number}.mkv")
    make("more/Alpha S01E04.mkv")
    make("more/Beta S01E01.mkv")
    return {"alpha": tmp_path / "Alpha", "more": tmp_path / "more"}


def load_and_wait(controller: WindowController, folder: Path, qtbot: QtBot) -> None:
    controller.add_paths([folder])
    qtbot.waitUntil(lambda: not controller.busy)


def start_reading(controller: WindowController, loader: LibraryLoader, folder: Path, qtbot: QtBot) -> None:
    """Add `folder` and wait until the window has been told which videos the load will read."""
    with qtbot.waitSignal(loader.scanned):
        controller.add_paths([folder])
    qtbot.wait(20)


def test_the_open_place_waits_while_its_own_files_are_read_and_no_longer(
    controller: WindowController, loader: LibraryLoader, folders: dict[str, Path], read: Held, qtbot: QtBot
) -> None:
    load_and_wait(controller, folders["alpha"], qtbot)
    assert not controller.reading_open_batch
    read.held = {"Alpha S01E04.mkv"}
    start_reading(controller, loader, folders["more"], qtbot)
    assert controller.busy
    assert controller.reading_open_batch
    read.held = set()
    qtbot.waitUntil(lambda: not controller.busy)
    assert not controller.reading_open_batch


def test_another_place_still_being_read_does_not_block_the_open_one(
    controller: WindowController, loader: LibraryLoader, folders: dict[str, Path], read: Held, qtbot: QtBot
) -> None:
    load_and_wait(controller, folders["alpha"], qtbot)
    read.held = {"Beta S01E01.mkv"}
    # Alpha's fourth episode is read first and Beta's is held: the open place is done, the load is not.
    start_reading(controller, loader, folders["more"], qtbot)
    qtbot.waitUntil(lambda: controller.job_text == "Reading tracks 1 of 2")
    assert controller.busy
    assert not controller.reading_open_batch


def test_a_load_of_another_show_alone_never_blocks(
    controller: WindowController, loader: LibraryLoader, folders: dict[str, Path], read: Held, qtbot: QtBot
) -> None:
    load_and_wait(controller, folders["alpha"], qtbot)
    (folders["more"] / "Alpha S01E04.mkv").unlink()
    read.held = {"Beta S01E01.mkv"}
    start_reading(controller, loader, folders["more"], qtbot)
    assert controller.busy
    assert not controller.reading_open_batch


def test_cancel_unblocks_the_workspace_at_once(
    controller: WindowController, loader: LibraryLoader, folders: dict[str, Path], read: Held, qtbot: QtBot
) -> None:
    load_and_wait(controller, folders["alpha"], qtbot)
    read.held = {"Alpha S01E04.mkv"}
    start_reading(controller, loader, folders["more"], qtbot)
    assert controller.reading_open_batch
    controller.cancel_reading()
    assert not controller.reading_open_batch
    qtbot.waitUntil(lambda: not controller.busy)


def test_the_first_read_and_the_read_after_closing_the_folder_wait_for_the_place_that_opens(
    controller: WindowController, loader: LibraryLoader, folders: dict[str, Path], read: Held, qtbot: QtBot
) -> None:
    save_settings(replace(load_settings().value, last_folders=[str(folders["alpha"])]))
    read.held = {"Alpha S01E02.mkv"}
    with qtbot.waitSignal(loader.scanned):
        controller.restore_workspace()
    assert controller.reading_open_batch
    read.held = set()
    qtbot.waitUntil(lambda: not controller.busy)
    assert not controller.reading_open_batch
    controller.close_folder()
    read.held = {"Alpha S01E02.mkv"}
    controller.add_paths([folders["alpha"]])
    assert controller.reading_open_batch
    read.held = set()
    qtbot.waitUntil(lambda: not controller.busy)
    assert not controller.reading_open_batch


def part(load: Any, name: str) -> QQuickItem:
    return load.window.findChild(QQuickItem, name)


def click(load: Any, item: QQuickItem) -> None:
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def test_the_overlay_covers_and_blocks_the_workspace_and_cancel_ends_it(
    controller: WindowController,
    loader: LibraryLoader,
    folders: dict[str, Path],
    read: Held,
    load: Any,
    qtbot: QtBot,
) -> None:
    load_and_wait(controller, folders["alpha"], qtbot)
    load()
    overlay = part(load, "loadingOverlay")
    exclude = part(load, "excludeBatch")
    assert not overlay.isVisible()
    assert exclude.isEnabled()
    read.held = {"Alpha S01E04.mkv"}
    start_reading(controller, loader, folders["more"], qtbot)
    load()
    assert overlay.isVisible()
    assert part(load, "overlayText").property("text") == controller.job_text
    assert part(load, "overlayProgress").isVisible()
    assert part(load, "cancelReading").isVisible()  # the status bar still shows the reading

    # A click that lands on the workspace goes no further than the layer.
    assert not exclude.isEnabled()
    click(load, exclude)
    assert not controller.place_excluded

    # Cancel has the focus, so the keyboard reaches it; Escape presses it.
    assert part(load, "overlayCancel").property("activeFocus") is True
    QTest.keyClick(load.window, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not controller.busy)
    load()
    assert not overlay.isVisible()
    assert exclude.isEnabled()


def test_the_layer_over_home_is_named_for_screen_readers_and_cancel_works_by_click(
    controller: WindowController,
    loader: LibraryLoader,
    folders: dict[str, Path],
    read: Held,
    load: Any,
    qtbot: QtBot,
) -> None:
    save_settings(replace(load_settings().value, last_folders=[str(folders["alpha"])]))
    read.held = {"Alpha S01E02.mkv"}
    with qtbot.waitSignal(loader.scanned):
        controller.restore_workspace()
    load()
    overlay = part(load, "loadingOverlay")
    assert overlay.isVisible()
    assert not controller.loaded  # Home lies under the layer
    QAccessible.setActive(True)
    accessible = QAccessible.queryAccessibleInterface(overlay)
    assert accessible is not None
    assert accessible.role() == QAccessible.Role.ProgressBar
    assert accessible.text(QAccessible.Text.Name) == "Reading the library"
    click(load, part(load, "overlayCancel"))
    qtbot.waitUntil(lambda: not controller.busy)
    load()
    assert not overlay.isVisible()
