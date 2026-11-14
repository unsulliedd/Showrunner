from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, Movie
from showrunner.core.naming import NamingContext
from showrunner.core.track import (
    AudioProperties,
    HdrKind,
    ObjectAudio,
    SubtitleProperties,
    Track,
    TrackFlags,
    TrackKind,
    VideoProperties,
)

# Test modules in mirrored folders cannot import each other, so the sample builders are fixtures.
BASE = "Show Name (2020) - 1x05 - Episode Name"


def _video(
    width: int = 1920,
    height: int = 1080,
    hdr: HdrKind = HdrKind.NONE,
    bit_depth: int | None = 10,
    codec: str = "V_MPEGH/ISO/HEVC",
) -> Track:
    return Track(0, TrackKind.VIDEO, codec, video=VideoProperties(width, height, 23.976, hdr, bit_depth))


def _audio(
    codec: str = "A_EAC3",
    channels: int = 6,
    object_audio: ObjectAudio = ObjectAudio.NONE,
    track_id: int = 1,
    **flags: bool,
) -> Track:
    return Track(
        track_id,
        TrackKind.AUDIO,
        codec,
        Language.parse("eng"),
        "Original Name",
        TrackFlags(**flags),
        audio=AudioProperties(channels, 48000, object_audio),
    )


def _subtitle(track_id: int = 2) -> Track:
    return Track(track_id, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language.parse("tur"), subtitle=SubtitleProperties())


def _make_item(*tracks: Track, stem: str = BASE, movie: bool = False) -> MediaItem:
    identity = Movie("Movie Title", 2021) if movie else Episode("Show Name", 1, 5, 2020, "Episode Name")
    return MediaItem(identity, MediaFile(Path(f"{stem}.mkv"), "matroska", tracks=tracks))


@pytest.fixture
def base() -> str:
    return BASE


@pytest.fixture
def video() -> Callable[..., Track]:
    return _video


@pytest.fixture
def audio() -> Callable[..., Track]:
    return _audio


@pytest.fixture
def subtitle() -> Callable[..., Track]:
    return _subtitle


@pytest.fixture
def make_item() -> Callable[..., MediaItem]:
    return _make_item


@pytest.fixture
def episode_context() -> NamingContext:
    return NamingContext(_make_item(_video(), _audio(), _subtitle()))
