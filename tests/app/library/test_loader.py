from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.app.library.library import LibraryLoad
from showrunner.app.library.loader import LibraryLoader
from showrunner.core.media import MediaFile
from showrunner.tools.probe import Programs

PROGRAMS = Programs(Path("mkvmerge"))


def wait_until(condition: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.005)


def test_results_arrive_on_the_calling_thread(qapp: QApplication, make: Callable[..., Path], tmp_path: Path) -> None:
    make("Show/Show S01E01.mkv")
    make("Show/Show S01E02.mkv")
    reading_threads: set[int] = set()
    receiving_threads: set[int] = set()

    def read(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        reading_threads.add(threading.get_ident())
        return MediaFile(path, "matroska")

    loader = LibraryLoader(programs=PROGRAMS, read=read)
    progress: list[tuple[int, int]] = []
    loads: list[LibraryLoad] = []

    def on_progress(done: int, total: int) -> None:
        receiving_threads.add(threading.get_ident())
        progress.append((done, total))

    loader.progress.connect(on_progress)
    loader.finished.connect(loads.append)
    loader.start([tmp_path / "Show"])
    assert loader.busy
    wait_until(lambda: bool(loads))
    assert not loader.busy
    assert progress == [(1, 2), (2, 2)]
    assert len(loads[0].items) == 2
    assert threading.get_ident() not in reading_threads
    assert receiving_threads == {threading.get_ident()}


def test_cancel_stops_the_load_and_returns_what_was_reached(
    qapp: QApplication, make: Callable[..., Path], tmp_path: Path
) -> None:
    for number in range(1, 6):
        make(f"Show/Show S01E0{number}.mkv")
    release = threading.Event()
    reads: list[Path] = []

    def read(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        reads.append(path)
        if len(reads) == 2:
            release.wait(5)  # the second read is in progress while the test cancels
        return MediaFile(path, "matroska", duration=1.0)

    loader = LibraryLoader(programs=PROGRAMS, read=read)
    loads: list[LibraryLoad] = []
    progress: list[int] = []
    loader.finished.connect(loads.append)
    loader.progress.connect(lambda done, _total: progress.append(done))
    loader.start([tmp_path / "Show"])
    wait_until(lambda: progress == [1])
    loader.cancel()
    release.set()
    wait_until(lambda: bool(loads))
    assert loads[0].cancelled
    assert len(loads[0].items) == 5
    assert [i.file.duration for i in loads[0].items] == [1.0, 1.0, None, None, None]


def test_an_error_is_reported_through_failed(qapp: QApplication, tmp_path: Path) -> None:
    loader = LibraryLoader(programs=PROGRAMS)
    errors: list[Exception] = []
    loader.failed.connect(errors.append)
    loader.start([tmp_path / "Show"], known=object())  # type: ignore[arg-type]  # a bad argument fails inside the work
    wait_until(lambda: bool(errors))
    assert not loader.busy


def test_a_second_start_is_refused_while_running(qapp: QApplication, make: Callable[..., Path], tmp_path: Path) -> None:
    make("Show/Show S01E01.mkv")
    release = threading.Event()

    def read(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        release.wait(5)
        return MediaFile(path, "matroska")

    loader = LibraryLoader(programs=PROGRAMS, read=read)
    done: list[LibraryLoad] = []
    loader.finished.connect(done.append)
    loader.start([tmp_path / "Show"])
    with pytest.raises(RuntimeError):
        loader.start([tmp_path / "Show"])
    release.set()
    wait_until(lambda: bool(done))
