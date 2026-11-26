import os
import re
import shutil
import subprocess
import threading
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
from showrunner.tools.ai import AiError, ChatAnswer, ChatRequest, ErrorKind


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config: pytest.Config) -> int | None:
    """No workers for a run of tests named one by one (`path::name`): starting them takes longer than such a run."""
    return 0 if config.args and all("::" in arg for arg in config.args) else None


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


def find_program(name: str) -> Path | None:
    """A program on PATH, or MKVToolNix's in its default folder."""
    if found := shutil.which(name):
        return Path(found)
    folder = Path(os.environ.get("PROGRAMFILES", "")) / "MKVToolNix"
    return next(iter(folder.glob(f"{name}.exe")), None) if name.startswith("mkv") else None


# Turkish text in the code page such files were written in before UTF-8.
TURKISH_LINE = "Güzel şehir"


@dataclass(frozen=True)
class RealEpisode:
    """A small Matroska file made in `tmp_path`: video, English audio and French audio, with a Turkish subtitle
    file in Windows-1254 beside it."""

    video: Path
    subtitle: Path
    mkvmerge: Path


@pytest.fixture
def real_episode(tmp_path: Path) -> RealEpisode:
    ffmpeg, mkvmerge = find_program("ffmpeg"), find_program("mkvmerge")
    if ffmpeg is None or mkvmerge is None:
        pytest.skip("ffmpeg and MKVToolNix are needed")
    work = tmp_path / "work"
    work.mkdir()
    source = work / "source.mkv"
    subprocess.run(
        [
            ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=2",
            "-f", "lavfi", "-i", "sine=d=2", "-f", "lavfi", "-i", "sine=f=880:d=2",
            "-map", "0", "-map", "1", "-map", "2", "-c:v", "mpeg4", "-c:a", "aac", source,
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    folder = tmp_path / "Show Name" / "Season 01"
    folder.mkdir(parents=True)
    video = folder / "Show Name - S01E01.mkv"
    subprocess.run(
        [mkvmerge, "-o", video, "--language", "1:eng", "--language", "2:fre", "--title", "Old Title", source],
        check=True,
        capture_output=True,
    )
    subtitle = folder / "Show Name - S01E01.tr.srt"
    subtitle.write_bytes(f"1\r\n00:00:00,000 --> 00:00:01,000\r\n{TURKISH_LINE}\r\n".encode("cp1254"))
    return RealEpisode(video, subtitle, mkvmerge)


_OWN = re.compile(r"Translate these cues:\n(.*?)(?:\n\n|$)", re.S)


class Translator:
    """Answers each numbered cue with "tr " before it; a window whose first cue is in `bad` gets one cue too few, and
    one whose first cue is in `down` a timeout."""

    name = "fake"

    def __init__(self, bad: set[str] | None = None, down: set[str] | None = None) -> None:
        self.bad, self.down = bad or set(), down or set()
        self.asked: list[ChatRequest] = []

    def models(self) -> list[str]:
        return ["sample:9b"]

    def version(self) -> str:
        return "0"

    def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer:
        self.asked.append(request)
        own = _OWN.search(request.messages[0].content)
        assert own is not None
        blocks = re.split(r"^\[\d+\]\n", own.group(1), flags=re.M)[1:]
        first = blocks[0].strip()
        if first in self.down:
            raise AiError(ErrorKind.TIMEOUT, "300 s")
        if first in self.bad:
            blocks = blocks[:-1]
        return ChatAnswer("\n".join(f"[{n}]\ntr {b.strip()}" for n, b in enumerate(blocks, start=1)), 0.1)


@pytest.fixture
def translator() -> type[Translator]:
    """A stand-in AI backend that translates numbered cues, for the tests of the translate step."""
    return Translator
