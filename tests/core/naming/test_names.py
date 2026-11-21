from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.core.naming.names import (
    channel_layout,
    codec_display,
    guess_source,
    guess_source_of,
    hdr_display,
    resolution,
)
from showrunner.core.track import HdrKind, ObjectAudio


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((3840, 2160), "2160p"),
        ((3840, 1600), "2160p"),  # cropped scope
        ((4096, 2160), "2160p"),
        ((1920, 1080), "1080p"),
        ((1920, 800), "1080p"),
        ((1920, 1040), "1080p"),
        ((1440, 1080), "1080p"),  # 4:3 inside a 1080 frame
        ((1280, 720), "720p"),
        ((1280, 536), "720p"),
        ((720, 576), "576p"),
        ((1024, 576), "576p"),
        ((720, 480), "480p"),
        ((720, 400), "480p"),
        ((None, None), ""),
        ((0, 0), ""),
    ],
)
def test_resolution(size: tuple[int | None, int | None], expected: str) -> None:
    assert resolution(*size) == expected


@pytest.mark.parametrize(
    ("channels", "expected"),
    [(1, "1.0"), (2, "2.0"), (6, "5.1"), (8, "7.1"), (12, "12ch"), (None, ""), (0, "")],
)
def test_channel_layout(channels: int | None, expected: str) -> None:
    assert channel_layout(channels) == expected


def test_codec_names_default_and_fallback() -> None:
    assert codec_display("A_EAC3", ObjectAudio.NONE) == "Dolby Digital Plus"
    assert codec_display("A_UNKNOWN", ObjectAudio.NONE) == "A_UNKNOWN"


def test_object_audio_picks_the_specific_entry() -> None:
    assert codec_display("A_TRUEHD", ObjectAudio.ATMOS) == "Dolby Atmos"
    assert codec_display("A_EAC3", ObjectAudio.ATMOS) == "Dolby Digital Plus with Dolby Atmos"
    assert codec_display("A_DTS", ObjectAudio.DTS_X) == "DTS:X"
    # No entry for the combination: the plain codec name.
    assert codec_display("A_AAC", ObjectAudio.ATMOS) == "AAC"


def test_hdr_names() -> None:
    assert hdr_display(HdrKind.NONE) == ""
    assert hdr_display(HdrKind.HDR10_PLUS) == "HDR10+"


@pytest.mark.parametrize(
    ("release", "expected"),
    [
        ("Show.Name.S01E05.1080p.BluRay.x265-GRP", "BluRay"),
        ("Show Name 1x05 Blu-Ray", "BluRay"),
        ("Show.Name.S01E05.2160p.WEB-DL.DDP5.1.HEVC", "WEB-DL"),
        ("Show.Name.S01E05.WEBDL", "WEB-DL"),
        ("Show.Name.S01E05.1080p.WEBRip.x264", "WEBRip"),
        ("Show.Name.S01E05.WEB-Rip", "WEBRip"),
        ("Show.Name.S01E05.HDTV.x264", "HDTV"),
        ("Show.Name.S01E05.DVDRip.XviD", "DVD"),
        ("Show.Name.S01E05.2160p.Hybrid.WEB-DL", "Hybrid WEB-DL"),
        ("Movie.Title.2021.2160p.BluRay.REMUX", "BluRay REMUX"),
        ("Movie.Title.2021.Hybrid.BluRay.Remux", "Hybrid BluRay REMUX"),
        ("Show Name - 1x05 - Episode Name", ""),
        ("Anna's Web", ""),  # a bare WEB is a title word
        ("Subway.S01E05", ""),  # markers sit between non-alphanumerics only
    ],
)
def test_guess_source(release: str, expected: str) -> None:
    assert guess_source(release) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        # The file name wins over the folders.
        ("Library/Show Name [1080p BDRip x265]/Season 1/Show.Name.S01E05.WEB-DL.mkv", "WEB-DL"),
        # Nearest folder first: the season folder, then the release folder.
        ("Library/Show Name [1080p BDRip x265]/Season 1/Show Name - 1x05.mkv", "BluRay"),
        ("Library/Show Name [WEB-DL]/Season 1 [HDTV]/Show Name - 1x05.mkv", "HDTV"),
        ("Library/Show Name [1080p BDRip]/Show Name - 1x05.mkv", "BluRay"),
        # Three levels above the file at most.
        ("[BluRay]/Library/Show Name/Season 1/Show Name - 1x05.mkv", ""),
        ("Library/Show Name [BluRay]/Extras/Season 1/Show Name - 1x05.mkv", "BluRay"),
        ("Show Name - 1x05.mkv", ""),
    ],
)
def test_guess_source_of_looks_at_the_folders(path: str, expected: str) -> None:
    assert guess_source_of(Path(path)) == expected
