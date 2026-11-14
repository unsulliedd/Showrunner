from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from showrunner.tools.dependencies.detect import DependencyStatus, Location, State
from showrunner.ui.shell.empty_state import EmptyState
from showrunner.ui.theme.manager import ThemeManager


def texts(state: EmptyState) -> list[str]:
    return [label.text() for label in state.findChildren(QLabel)]


def test_dragging_over_the_state_switches_the_drop_look_and_names_the_folder(
    qapp: QApplication, theme: ThemeManager
) -> None:
    state = EmptyState()
    assert state.property("drop") == "idle"
    state.set_dragging("Show Name (2022)")
    assert state.property("drop") == "over"
    assert state.title.text() == "Release to scan Show Name (2022)"
    state.set_dragging(None)
    assert state.property("drop") == "idle"
    assert state.title.text() == "Drop a folder to start"


def test_the_line_names_the_programs_that_read_tracks(qapp: QApplication, theme: ThemeManager) -> None:
    state = EmptyState()
    found = {
        "mkvtoolnix": DependencyStatus("mkvtoolnix", State.FOUND, Path("mkvmerge"), Location.PATH, "88.0"),
        "ffmpeg": DependencyStatus("ffmpeg", State.FOUND, Path("ffprobe"), Location.PATH, "7.1"),
    }
    state.set_statuses(found)
    assert "Tracks are read with MKVToolNix 88.0 and FFmpeg 7.1." in texts(state)
    assert [b.text() for b in state.findChildren(QPushButton) if b.isFlat()] == ["Dependencies…"]


def test_a_missing_program_says_what_is_lost_in_the_notice_color(qapp: QApplication, theme: ThemeManager) -> None:
    state = EmptyState()
    state.set_statuses(
        {
            "mkvtoolnix": DependencyStatus("mkvtoolnix", State.MISSING),
            "ffmpeg": DependencyStatus("ffmpeg", State.FOUND, Path("ffprobe"), Location.PATH, "7.1"),
        }
    )
    notices = [label for label in state.findChildren(QLabel) if label.property("role") == "notice"]
    assert len(notices) == 1
    assert notices[0].text().startswith("MKVToolNix was not found.")
    state.set_statuses({})  # a second result replaces the first
    assert not [
        label for label in state.findChildren(QLabel) if label.property("role") == "notice" and label.isVisible()
    ]
