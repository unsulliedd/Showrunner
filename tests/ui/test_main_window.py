from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from showrunner.app.library.library import Library
from showrunner.app.library.loader import LibraryLoader
from showrunner.app.settings.app_settings import load_settings
from showrunner.core.media import MediaFile
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.probe import Programs
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.main_window import MainWindow
from showrunner.ui.theme.manager import ThemeManager

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def wait_until(condition: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.005)


def fake_read(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
    return MediaFile(path, "matroska", duration=60.0)


def statuses() -> dict[str, DependencyStatus]:
    # The window must not run the programs of the machine the tests run on.
    return {
        "mkvtoolnix": DependencyStatus("mkvtoolnix", State.MISSING),
        "ffmpeg": DependencyStatus("ffmpeg", State.MISSING),
    }


@pytest.fixture
def window(qapp: QApplication, theme: ThemeManager) -> MainWindow:
    loader = LibraryLoader(programs=Programs(Path("mkvmerge")), read=fake_read)
    window = MainWindow(theme, loader, statuses)
    window.show()
    return window


def urls(*paths: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def test_window_opens_and_closes(qapp: QApplication, theme: ThemeManager) -> None:
    window = MainWindow(theme, reader_statuses=statuses)
    window.show()
    assert window.isVisible()
    assert window.windowTitle() == tr("main_window.title") == "Showrunner"
    assert window.close()
    assert not window.isVisible()


def test_it_opens_on_the_empty_state(window: MainWindow) -> None:
    assert window.stack.currentWidget() is not None
    assert window.stack.currentIndex() == 0
    assert window.summary.texts() == ["No library loaded"]
    assert window.acceptDrops()


def test_the_empty_state_names_the_missing_programs(window: MainWindow) -> None:
    wait_until(lambda: window.empty._programs is not None)
    notices = [
        label.text()
        for label in window.empty.findChildren(type(window.empty.title))
        if label.property("role") == "notice"
    ]
    assert len(notices) == 2


def test_dropping_a_folder_loads_it_and_shows_the_library(
    window: MainWindow, make: Callable[..., Path], tmp_path: Path
) -> None:
    make("Show/S01/Show S01E01.mkv")
    make("Show/S01/Show S01E02.mkv")
    make("Show/S01/Show S01E01.tr.srt")
    mime = urls(tmp_path / "Show")
    window.dragEnterEvent(
        QDragEnterEvent(
            QPoint(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
    )
    assert window.empty.property("drop") == "over"
    window.dropEvent(
        QDropEvent(
            QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        )
    )
    assert window.empty.property("drop") == "idle"
    assert window.loading
    assert not window.add_button.isEnabled()
    wait_until(lambda: window.stack.currentIndex() == 1)
    assert not window.loading
    assert window.model.library.counts().episodes == 2
    assert window.summary.texts()[0] == "2 videos"
    assert not window.job.isVisible()


def test_a_drop_on_a_loaded_window_adds_to_the_library(
    window: MainWindow, make: Callable[..., Path], tmp_path: Path
) -> None:
    make("One/One S01E01.mkv")
    make("Two/Two S01E01.mkv")
    window.add_paths([tmp_path / "One"])
    wait_until(lambda: window.stack.currentIndex() == 1)
    window.add_paths([tmp_path / "Two", tmp_path / "One"])
    wait_until(lambda: window.model.library.counts().videos == 2)
    assert not window.loading
    assert window.model.library.counts().shows == 2


def test_selecting_a_video_or_a_group_fills_the_sheet(window: MainWindow, sample_library: Library) -> None:
    window.model.set_library(sample_library)
    window.panel.expand_default()
    window.stack.setCurrentIndex(1)
    window.panel.select(window.model.index_for_path(sample_library.items[1].file.path))
    assert window.sheet.title.text() == "Alpha S01E02 · Second"
    window.panel.select(window.model.index(0, 0))
    assert window.sheet.title.text() == "Alpha"
    assert window.sheet.group_area.isVisible()


def test_pairing_by_hand_updates_the_tree_the_sheet_and_the_counts(window: MainWindow, sample_library: Library) -> None:
    window.model.set_library(sample_library)
    window.stack.setCurrentIndex(1)
    second = sample_library.items[1].file.path
    window.panel.select(window.model.index_for_path(second))
    assert "1 unsure pairing" in window.summary.texts()[2]
    window.sheet.pair_instead_requested.emit(second, sample_library.alternatives_of(second)[0])
    assert window.sheet.state.text() == ""
    assert not any("unsure" in text for text in window.summary.texts())
    assert window.panel.needs_look.text() == "Needs a look 1"
    window.sheet.unpair_requested.emit(window.model.library.item(second).subtitles[0])
    assert any("unpaired" in text for text in window.summary.texts())


def test_cancel_stops_a_running_load(window: MainWindow, make: Callable[..., Path], tmp_path: Path) -> None:
    for number in range(1, 4):
        make(f"Show/Show S01E0{number}.mkv")
    release = threading.Event()

    def slow(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        release.wait(5)
        return MediaFile(path, "matroska", duration=60.0)

    window._loader._read = slow
    window.add_paths([tmp_path / "Show"])
    assert window.job.isVisible()
    window.job.cancel.click()
    assert not window.job.cancel.isEnabled()
    release.set()
    wait_until(lambda: not window.loading)
    assert window.stack.currentIndex() == 1
    assert window.statusBar().currentMessage() == tr("status.cancelled")


def test_a_folder_without_videos_says_so_and_stays_empty(window: MainWindow, tmp_path: Path) -> None:
    window.add_paths([tmp_path])
    wait_until(lambda: not window.loading)
    assert window.stack.currentIndex() == 0
    assert window.statusBar().currentMessage() == tr("status.nothing_new")


def test_closing_a_loaded_window_saves_the_pane_sizes(window: MainWindow, sample_library: Library) -> None:
    window.model.set_library(sample_library)
    window.stack.setCurrentIndex(1)
    window.panel.select(window.model.index_for_path(sample_library.items[0].file.path))
    window.splitter.setSizes([300, 900])
    window.sheet.splitter.setSizes([700, 200])
    library_sizes, sheet_sizes = window.splitter.sizes(), window.sheet.splitter.sizes()
    window.close()
    assert load_settings().value.library_splitter == library_sizes
    assert load_settings().value.sheet_splitter == sheet_sizes


def test_saved_pane_sizes_are_restored_when_the_library_is_shown(qapp: QApplication, theme: ThemeManager) -> None:
    first = MainWindow(theme, reader_statuses=statuses)
    first.show()
    first.stack.setCurrentIndex(1)
    first.splitter.setSizes([400, 800])
    first.close()
    second = MainWindow(theme, reader_statuses=statuses)
    second.show()
    second.stack.setCurrentIndex(1)
    QApplication.processEvents()
    sizes = second.splitter.sizes()
    assert sizes[0] / sum(sizes) == pytest.approx(400 / 1200, abs=0.02)


def test_an_empty_window_does_not_overwrite_the_saved_sizes(qapp: QApplication, theme: ThemeManager) -> None:
    window = MainWindow(theme, reader_statuses=statuses)
    window.show()
    window.close()
    assert load_settings().value.library_splitter == []
