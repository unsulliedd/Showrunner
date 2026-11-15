from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import (
    AudioProperties,
    SubtitleProperties,
    Track,
    TrackFlags,
    TrackKind,
    VideoProperties,
)


def video(track_id: int = 0, name: str = "") -> Track:
    return Track(
        track_id,
        TrackKind.VIDEO,
        "V_MPEGH/ISO/HEVC",
        name=name,
        video=VideoProperties(1920, 1080, 23.976, bit_depth=10),
    )


def audio(track_id: int, name: str = "", language: str | None = "eng", **flags: bool) -> Track:
    return Track(
        track_id,
        TrackKind.AUDIO,
        "A_AC3",
        Language.parse(language) if language else None,
        name,
        TrackFlags(**flags),
        audio=AudioProperties(6),
    )


def subtitle(track_id: int, name: str = "", language: str | None = "eng", **flags: bool) -> Track:
    return Track(
        track_id,
        TrackKind.SUBTITLE,
        "S_TEXT/UTF8",
        Language.parse(language) if language else None,
        name,
        TrackFlags(**flags),
        subtitle=SubtitleProperties(),
    )


def make_item(
    *tracks: Track,
    title: str = "",
    container: str = "Matroska",
    ids_from_mkvmerge: bool = True,
    subtitles: tuple[SubtitleFile, ...] = (),
) -> MediaItem:
    file = MediaFile(
        Path("Show Name - S01E01.mkv"),
        container,
        title=title,
        tracks=tracks,
        ids_from_mkvmerge=ids_from_mkvmerge,
    )
    return MediaItem(Episode("Show Name", 1, 1), file, subtitles)


@pytest.fixture
def b() -> SimpleNamespace:
    # Test modules in mirrored folders cannot import each other, so the sample builders are a fixture.
    return SimpleNamespace(video=video, audio=audio, subtitle=subtitle, item=make_item)
