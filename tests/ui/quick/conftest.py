"""Fixtures for the Qt Quick window, and a neutral library: two shows and three movies with made-up names, read from
no file. The screenshot script imports the library and the program statuses from here too."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QtMsgType
from PySide6.QtWidgets import QApplication

from showrunner.app.library.library import Library
from showrunner.core.language import Language
from showrunner.core.media import Attachment, Chapter, Episode, MediaFile, MediaItem, Movie, SubtitleFile
from showrunner.core.track import (
    AudioProperties,
    HdrKind,
    SubtitleProperties,
    Track,
    TrackFlags,
    TrackKind,
    VideoProperties,
)
from showrunner.stages.scan import Alternatives
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.ui.quick.window import WindowController

NUMBERS = ("One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")
GB = 1024**3


def _file(path: Path, size: float, duration: float, hdr: HdrKind, chapters: int, attachments: int) -> MediaFile:
    tracks = (
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(3840, 2160, 23.976, hdr, 10)),
        Track(
            1, TrackKind.AUDIO, "A_EAC3", Language("eng"), "English", TrackFlags(default=True), audio=AudioProperties(6)
        ),
        Track(2, TrackKind.AUDIO, "A_EAC3", Language("tur"), "Turkish", audio=AudioProperties(6)),
        Track(3, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), "English", subtitle=SubtitleProperties()),
    )
    return MediaFile(
        path,
        "matroska",
        duration,
        int(size * GB),
        tracks=tracks,
        chapters=tuple(Chapter(i * 300.0) for i in range(chapters)),
        attachments=tuple(Attachment(i + 1, f"font{i}.ttf", "font/ttf", 50_000) for i in range(attachments)),
    )


def _episode(show: str, year: int, season: int, number: int) -> MediaItem:
    folder = Path(f"{show} ({year})") / f"Season {season}"
    stem = f"{show.replace(' ', '.')}.S{season:02d}E{number:02d}"
    title = f"Episode {NUMBERS[number - 1]}" if number <= len(NUMBERS) else ""
    file = _file(folder / f"{stem}.mkv", 6.43, 3134.0, HdrKind.DOLBY_VISION, 8, 2)
    subtitles = (SubtitleFile(folder / f"{stem}.tur.srt", Language("tur")),)
    return MediaItem(Episode(show, season, number, year, title), file, subtitles)


def _movie(title: str, year: int, subtitles: bool) -> MediaItem:
    folder = Path(f"{title} ({year})")
    file = _file(folder / f"{title.replace(' ', '.')}.{year}.mkv", 58.3, 8048.0, HdrKind.HDR10, 12, 0)
    paired = (SubtitleFile(folder / f"{title}.tur.srt", Language("tur")),) if subtitles else ()
    return MediaItem(Movie(title, year), file, paired)


def neutral_library() -> Library:
    """Show Name (2020) with seasons of 10 and 8 episodes, Another Show (2018) with 24, and three movies. The scan
    was unsure of Episode Seven's subtitle file."""
    items = [_episode("Show Name", 2020, 1, n) for n in range(1, 11)]
    items += [_episode("Show Name", 2020, 2, n) for n in range(1, 9)]
    items += [_episode("Another Show", 2018, s, n) for s in (1, 2, 3) for n in range(1, 9)]
    items += [
        _movie("Movie Title", 2021, True),
        _movie("Another Movie", 2019, False),
        _movie("Third Movie", 2016, True),
    ]
    seventh = items[6]
    doubt = Alternatives(
        seventh.file.path, (SubtitleFile(seventh.file.path.with_suffix(".web.tur.srt"), Language("tur")),)
    )
    return Library(tuple(items), (doubt,))


def program_statuses() -> dict[str, DependencyStatus]:
    """MKVToolNix found, FFmpeg missing, as on the approved first-run screen."""
    return {
        "mkvtoolnix": DependencyStatus("mkvtoolnix", State.FOUND, version="88.0"),
        "ffmpeg": DependencyStatus("ffmpeg", State.MISSING),
    }


@pytest.fixture
def library() -> Library:
    return neutral_library()


@pytest.fixture
def opened() -> list[str]:
    """The programs whose "Get it" was pressed."""
    return []


@pytest.fixture
def controller(qapp: QApplication, opened: list[str]) -> Iterator[WindowController]:
    """A window controller with the programs stubbed; the data folder is the test's own (see `data_home`)."""
    controller = WindowController(statuses=program_statuses, get_program=opened.append)
    yield controller
    controller.deleteLater()


@pytest.fixture
def qt_warnings(qtlog: Any) -> Callable[[], list[str]]:
    """The warnings and errors Qt logged so far, without the offscreen platform's note that it has no font folder."""
    return lambda: [
        record.message
        for record in qtlog.records
        if record.type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
        and "font directory" not in record.message
        and "no longer ships fonts" not in record.message
    ]
