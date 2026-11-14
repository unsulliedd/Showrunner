from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import AudioProperties, ObjectAudio, SubtitleProperties, Track, TrackFlags, TrackKind


def video(id: int = 0, **kwargs: object) -> Track:
    return Track(id, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", **kwargs)  # type: ignore[arg-type]


def audio(
    id: int,
    codec: str = "A_AAC",
    language: Language | None = None,
    channels: int | None = 2,
    *,
    name: str = "",
    object_audio: ObjectAudio = ObjectAudio.NONE,
    **flags: bool,
) -> Track:
    return Track(
        id,
        TrackKind.AUDIO,
        codec,
        language,
        name,
        TrackFlags(**flags),
        audio=AudioProperties(channels=channels, object_audio=object_audio),
    )


def subtitle(
    id: int, language: Language | None = None, codec: str = "S_TEXT/UTF8", *, name: str = "", **flags: bool
) -> Track:
    return Track(id, TrackKind.SUBTITLE, codec, language, name, TrackFlags(**flags), subtitle=SubtitleProperties())


def item(*tracks: Track, subtitles: tuple[SubtitleFile, ...] = ()) -> MediaItem:
    file = MediaFile(Path("Show Name - S01E01.mkv"), "matroska", tracks=tracks)
    return MediaItem(Episode("Show Name", 1, 1), file, subtitles)


def srt(language: Language | None, **kwargs: bool) -> SubtitleFile:
    tags = ([language.ietf] if language else []) + [name for name, on in kwargs.items() if on]
    return SubtitleFile(Path("".join(["Show Name - S01E01", *(f".{tag}" for tag in tags), ".srt"])), language, **kwargs)


# Test modules in mirrored folders cannot import each other, so the sample builders are one fixture.
@pytest.fixture
def b() -> SimpleNamespace:
    return SimpleNamespace(
        video=video,
        audio=audio,
        subtitle=subtitle,
        item=item,
        srt=srt,
        en=Language.parse("en"),
        tr=Language.parse("tr"),
        pt_br=Language.parse("pt-BR"),
    )
