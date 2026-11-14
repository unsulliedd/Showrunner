import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

# Must be set before Qt loads a platform plugin: renders to memory, so tests need no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.app.library.library import Library
from showrunner.core.language import Language
from showrunner.core.media import Attachment, Chapter, ChapterName, Episode, MediaFile, MediaItem, Movie, SubtitleFile
from showrunner.core.options.registry import OptionsRegistry
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackFlags, TrackKind, VideoProperties
from showrunner.stages.scan import Alternatives, ProbeFailure


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    # Qt allows one QApplication per process, so it is shared by every test.
    return QApplication.instance() or QApplication([])


class Mode(StrEnum):
    FAST = "fast"
    SLOW = "slow"


# Stands in for a real stage: one field of each supported kind.
@dataclass(frozen=True)
class ExampleOptions:
    enabled: bool = True
    flag: bool = False
    count: int = 3
    ratio: float = 0.5
    label: str = "x"
    mode: Mode = Mode.FAST
    names: list[str] = field(default_factory=lambda: ["a", "b"])
    modes: list[Mode] = field(default_factory=list)


@pytest.fixture
def registry() -> OptionsRegistry:
    registry = OptionsRegistry()
    registry.register("example")(ExampleOptions)
    return registry


@pytest.fixture
def example() -> type[ExampleOptions]:
    return ExampleOptions


@pytest.fixture
def mode() -> type[Mode]:
    return Mode


def subtitle(name: str, language: str = "tur", *, forced: bool = False) -> SubtitleFile:
    return SubtitleFile(Path("lib/Alpha/S01") / name, Language(language), forced=forced)


def video(path: str, identity: Episode | Movie, subtitles: tuple[SubtitleFile, ...] = ()) -> MediaItem:
    tracks = (
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080, 23.976, bit_depth=10)),
        Track(
            1, TrackKind.AUDIO, "A_AC3", Language("eng"), "AC-3 5.1", TrackFlags(default=True), audio=AudioProperties(6)
        ),
        Track(
            2,
            TrackKind.SUBTITLE,
            "S_TEXT/UTF8",
            Language("eng"),
            flags=TrackFlags(forced=True),
            subtitle=SubtitleProperties(),
        ),
    )
    chapters = (Chapter(0.0, names=(ChapterName(None, "Intro"),)), Chapter(185.0))
    attachments = (Attachment(1, "cover.jpg", "image/jpeg", 214_000),)
    file = MediaFile(
        Path(path), "matroska", 1327.0, 952_000_000, tracks=tracks, chapters=chapters, attachments=attachments
    )
    return MediaItem(identity, file, subtitles)


@pytest.fixture
def sample_library() -> Library:
    """Two shows and a movie: one pairing the scan was unsure of, one file that could not be read, one
    subtitle file that fits no video."""
    first = video(
        "lib/Alpha/S01/Alpha S01E01.mkv", Episode("Alpha", 1, 1, 2020, "Pilot"), (subtitle("Alpha S01E01.tr.srt"),)
    )
    second = video(
        "lib/Alpha/S01/Alpha S01E02.mkv", Episode("Alpha", 1, 2, 2020, "Second"), (subtitle("Alpha S01E02.tr.srt"),)
    )
    third = video("lib/Alpha/S02/Alpha S02E01.mkv", Episode("Alpha", 2, 1, 2020))
    broken = video("lib/Beta/Beta S01E01.mkv", Episode("Beta", 1, 1))
    movie = video("lib/Movies/Movie Title (2016).mkv", Movie("Movie Title", 2016))
    return Library(
        (first, second, third, broken, movie),
        (Alternatives(second.file.path, (subtitle("Alpha S01E02 WEB.tr.srt"),)),),
        (subtitle("Alpha S01 extras.eng.srt", "eng"),),
        (ProbeFailure(broken.file.path, "broken header"),),
        (Path("lib"),),
    )


@pytest.fixture
def make(tmp_path: Path) -> Callable[..., Path]:
    """Create a file below `tmp_path` and return its path; the content only has to exist unless a test reads it."""

    def make_file(relative: str, content: bytes = b"x") -> Path:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    return make_file
