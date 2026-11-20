"""Fixtures for the Qt Quick window, and a neutral library: two shows and three movies with made-up names, read from
no file. The screenshot script imports the library and the program statuses from here too."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QtMsgType
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

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
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.window import WindowController

NUMBERS = ("One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")
GB = 1024**3
# The sample season's track columns, in the order Overview and Tracks list them.
VIDEO, ENGLISH, TURKISH, COMMENTARY, STEREO, SDH, ENGLISH_SUBS, FORCED, SRT = range(9)


def _tracks(number: int) -> tuple[Track, ...]:
    """English and Turkish audio with an English commentary, English SDH and plain subtitles and Turkish forced ones.
    Episode Seven has no Turkish audio and no forced subtitles; Episode Nine has an extra English stereo track."""
    tracks = [
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(3840, 2160, 23.976, HdrKind.NONE, 10)),
        Track(
            1, TrackKind.AUDIO, "A_EAC3", Language("eng"), "English", TrackFlags(default=True), audio=AudioProperties(6)
        ),
        Track(2, TrackKind.AUDIO, "A_EAC3", Language("tur"), "Turkish", audio=AudioProperties(6)),
        Track(3, TrackKind.AUDIO, "A_AC3", Language("eng"), "Commentary", audio=AudioProperties(2)),
        Track(
            4,
            TrackKind.SUBTITLE,
            "S_TEXT/UTF8",
            Language("eng"),
            "SDH",
            TrackFlags(hearing_impaired=True),
            subtitle=SubtitleProperties(),
        ),
        Track(5, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), "English", subtitle=SubtitleProperties()),
        Track(
            6,
            TrackKind.SUBTITLE,
            "S_TEXT/UTF8",
            Language("tur"),
            "Forced",
            TrackFlags(forced=True),
            subtitle=SubtitleProperties(),
        ),
    ]
    if number == 7:
        tracks = [t for t in tracks if t.id not in (2, 6)]
    if number == 9:
        tracks.append(Track(7, TrackKind.AUDIO, "A_AAC", Language("eng"), "Stereo", audio=AudioProperties(2)))
    return tuple(tracks)


def _file(
    path: Path, size: float, duration: float, hdr: HdrKind, chapters: int, attachments: int, number: int = 0
) -> MediaFile:
    tracks = _tracks(number)
    video = tracks[0]
    assert video.video is not None
    tracks = (replace(video, video=replace(video.video, hdr=hdr)), *tracks[1:])
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
    file = _file(folder / f"{stem}.mkv", 6.43, 3134.0, HdrKind.DOLBY_VISION, 8, 2, number)
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


def long_show(seasons: int = 12, episodes: int = 25, *, named_per_episode: bool = False) -> Library:
    """One show of `seasons` seasons of `episodes` episodes each (300 by default), with the sample's track set, for
    timing the whole show against one season. With `named_per_episode`, every track is named after its episode
    ("Long Show - 1x01 - Episode One (English)"), as some releases do."""
    items = [_episode("Long Show", 2001, s, n) for s in range(1, seasons + 1) for n in range(1, episodes + 1)]
    if named_per_episode:
        items = [named_after_episode(i) for i in items]
    return Library(tuple(items))


def named_after_episode(item: MediaItem) -> MediaItem:
    """The item with each track named after its episode, the track's own name in brackets."""
    identity = item.identity
    assert isinstance(identity, Episode)
    prefix = f"{identity.show} - {identity.season}x{identity.episode:02d} - {identity.episode_title}"
    tracks = tuple(replace(t, name=f"{prefix} ({t.name})" if t.name else prefix) for t in item.file.tracks)
    return replace(item, file=replace(item.file, tracks=tracks))


def program_statuses() -> dict[str, DependencyStatus]:
    """MKVToolNix found, FFmpeg missing, as on the approved first-run screen. The path is made up: plans name the
    program, nothing runs it."""
    return {
        "mkvtoolnix": DependencyStatus("mkvtoolnix", State.FOUND, Path("mkvtoolnix") / "mkvmerge", version="88.0"),
        "ffmpeg": DependencyStatus("ffmpeg", State.MISSING),
    }


def cells(controller: WindowController) -> list[list[dict[str, Any]]]:
    """Per file of the batch, what each track column holds for it, as the views build their marks from."""
    view = controller._view
    assert view is not None
    return [view.cells(item) for item in view.items]


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


@pytest.fixture
def load(controller: WindowController, qtbot: QtBot) -> Iterator[Any]:
    """Load the window; calling the result settles it and gives the QML warnings so far. `window` and `run` (a QML
    expression evaluated in the window's own scope) hang off it. The window closes after the test."""
    warnings: list[str] = []
    engine = build_engine(controller, on_warnings=lambda errors: warnings.extend(e.toString() for e in errors))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    qtbot.waitUntil(window.isExposed)

    def settle() -> list[str]:
        qtbot.wait(50)
        return warnings

    def run(source: str) -> object:
        expression = QQmlExpression(QQmlEngine.contextForObject(window), window, source)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value[0] if isinstance(value, tuple) else value

    settle.window = window  # type: ignore[attr-defined]
    settle.run = run  # type: ignore[attr-defined]
    yield settle
    window.close()
    engine.deleteLater()
