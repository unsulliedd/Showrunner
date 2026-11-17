"""Reading folders in the window: the status bar shows the files read of how many, a bar and Cancel."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.library.loader import LibraryLoader
from showrunner.app.settings.app_settings import load_settings, save_settings
from showrunner.app.storage.paths import read_cache_path
from showrunner.core.media import MediaFile
from showrunner.core.track import Track, TrackKind
from showrunner.tools.probe import Programs
from showrunner.tools.process import ProcessCancelledError
from showrunner.ui.quick.window import WindowController

from .conftest import program_statuses


class Gated:
    """Reads the first file at once and holds every later one until `gate` opens or the read is cancelled."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.calls: list[Path] = []

    def __call__(self, path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        self.calls.append(path)
        while self.calls[1:] and not self.gate.is_set():
            if cancel is not None and cancel.is_set():
                raise ProcessCancelledError("cancelled", ())
            time.sleep(0.005)
        return MediaFile(path, "Matroska", tracks=(Track(0, TrackKind.VIDEO, "V_MPEG4/ISO/AVC"),))


@pytest.fixture
def read() -> Iterator[Gated]:
    read = Gated()
    yield read
    read.gate.set()  # no pool thread is left waiting after the test


@pytest.fixture
def controller(qapp: QApplication, opened: list[str], read: Gated) -> Iterator[WindowController]:
    loader = LibraryLoader(programs=Programs(Path("mkvmerge")), read=read, cache=read_cache_path())
    controller = WindowController(statuses=program_statuses, loader=loader, get_program=opened.append)
    yield controller
    controller.deleteLater()


@pytest.fixture
def show(make: Callable[..., Path], tmp_path: Path) -> Path:
    for number in range(1, 4):
        make(f"Show/Show S01E0{number}.mkv")
    return tmp_path / "Show"


def status_part(load: Any, name: str) -> QQuickItem:
    return load.window.findChild(QQuickItem, name)


def wait_for_first_file(controller: WindowController, qtbot: QtBot) -> None:
    qtbot.waitUntil(lambda: controller.job_text == "Reading tracks 1 of 3")


def assert_progress_shows(load: Any) -> None:
    load()
    assert status_part(load, "jobText").property("text") == "Reading tracks 1 of 3"
    bar = status_part(load, "readProgress")
    assert bar.isVisible()
    assert bar.property("value") == pytest.approx(1 / 3)
    assert status_part(load, "cancelReading").isVisible()


def test_adding_a_folder_shows_its_progress_and_cancel_stops_the_read(
    controller: WindowController, load: Any, show: Path, read: Gated, qtbot: QtBot
) -> None:
    load()
    assert not status_part(load, "readProgress").isVisible()
    assert not status_part(load, "cancelReading").isVisible()
    controller.add_paths([show])
    wait_for_first_file(controller, qtbot)
    assert_progress_shows(load)

    cancel = status_part(load, "cancelReading")
    point = cancel.mapToScene(QPointF(cancel.width() / 2, cancel.height() / 2)).toPoint()
    QTest.mouseClick(load.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    qtbot.waitUntil(lambda: not controller.busy)
    load()
    assert len(read.calls) == 2  # the file being read when Cancel came was the last
    assert controller.job_text == "Reading cancelled. The videos it did not reach show as not read."
    assert not status_part(load, "readProgress").isVisible()
    items = controller.model.library.items
    assert [bool(i.file.tracks) for i in items] == [True, False, False]
    assert controller.model.library.failures == ()
    # What was read before Cancel is kept for the next start.
    entries = json.loads(read_cache_path().read_text(encoding="utf-8"))["entries"]
    assert [Path(k).name for k in entries] == ["Show S01E01.mkv"]


def test_the_last_folders_show_their_progress_at_start(
    controller: WindowController, load: Any, show: Path, read: Gated, qtbot: QtBot
) -> None:
    save_settings(replace(load_settings().value, last_folders=[str(show)]))
    load()
    controller.restore_workspace()
    wait_for_first_file(controller, qtbot)
    assert_progress_shows(load)
    read.gate.set()
    qtbot.waitUntil(lambda: not controller.busy)
    load()
    assert len(controller.model.library.items) == 3
    assert not status_part(load, "cancelReading").isVisible()


def test_a_second_start_reads_only_what_changed(
    controller: WindowController, show: Path, read: Gated, qtbot: QtBot
) -> None:
    read.gate.set()
    controller.add_paths([show])
    qtbot.waitUntil(lambda: not controller.busy)
    (show / "Show S01E02.mkv").write_bytes(b"changed")
    read.calls.clear()
    again = WindowController(
        statuses=program_statuses,
        loader=LibraryLoader(programs=Programs(Path("mkvmerge")), read=read, cache=read_cache_path()),
    )
    again.add_paths([show])
    qtbot.waitUntil(lambda: not again.busy)
    assert [p.name for p in read.calls] == ["Show S01E02.mkv"]
    assert all(i.file.tracks for i in again.model.library.items)
    again.deleteLater()
