"""Media files, what they are, and the files found beside them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.track import Track, TrackKind


@dataclass(frozen=True, slots=True)
class ChapterName:
    language: Language | None
    text: str


@dataclass(frozen=True, slots=True)
class Chapter:
    start: float  # seconds
    end: float | None = None
    names: tuple[ChapterName, ...] = ()

    def name_for(self, language: Language | None) -> str | None:
        """The name in the language, else the first name, else None."""
        for entry in self.names:
            if entry.language == language:
                return entry.text
        return self.names[0].text if self.names else None


@dataclass(frozen=True, slots=True)
class Attachment:
    id: int
    file_name: str
    mime_type: str
    size: int  # bytes
    description: str = ""


@dataclass(frozen=True, slots=True)
class MediaFile:
    path: Path
    container: str
    duration: float | None = None  # seconds
    size: int = 0  # bytes
    title: str = ""
    tracks: tuple[Track, ...] = ()
    chapters: tuple[Chapter, ...] = ()
    attachments: tuple[Attachment, ...] = ()

    def _of_kind(self, kind: TrackKind) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.kind is kind)

    @property
    def video_tracks(self) -> tuple[Track, ...]:
        return self._of_kind(TrackKind.VIDEO)

    @property
    def audio_tracks(self) -> tuple[Track, ...]:
        return self._of_kind(TrackKind.AUDIO)

    @property
    def subtitle_tracks(self) -> tuple[Track, ...]:
        return self._of_kind(TrackKind.SUBTITLE)


@dataclass(frozen=True, slots=True)
class Movie:
    title: str
    year: int | None = None


@dataclass(frozen=True, slots=True)
class Episode:
    show: str
    season: int
    episode: int
    year: int | None = None  # of the show
    episode_title: str = ""


@dataclass(frozen=True, slots=True)
class SubtitleFile:
    """A subtitle file beside a video; the flags come from its file name."""

    path: Path
    language: Language | None = None
    forced: bool = False
    sdh: bool = False


@dataclass(frozen=True, slots=True)
class MediaItem:
    """What a file is (a movie or an episode), the file itself and the subtitle files beside it."""

    identity: Movie | Episode
    file: MediaFile
    subtitles: tuple[SubtitleFile, ...] = ()
