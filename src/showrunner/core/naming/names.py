"""Display values judged from track properties: codec and HDR names, resolution, channel layout, source."""

from __future__ import annotations

import re
from pathlib import Path

from showrunner.core.track import HdrKind, ObjectAudio

# Keyed by Matroska codec ID. `<id>+atmos` and `<id>+dts-x` name a codec that carries object audio and win
# over the plain ID for such tracks. The track types hold no audio profile, so DTS core and DTS-HD Master
# Audio share `A_DTS`; a user who only has the HD variant rewrites `DTS` through a value map.
DEFAULT_CODEC_NAMES: dict[str, str] = {
    "V_MPEGH/ISO/HEVC": "HEVC",
    "V_MPEG4/ISO/AVC": "AVC",
    "V_MPEG2": "MPEG-2",
    "V_AV1": "AV1",
    "V_VP9": "VP9",
    "A_AAC": "AAC",
    "A_AC3": "Dolby Digital",
    "A_EAC3": "Dolby Digital Plus",
    "A_EAC3+atmos": "Dolby Digital Plus with Dolby Atmos",
    "A_TRUEHD": "Dolby TrueHD",
    "A_TRUEHD+atmos": "Dolby Atmos",
    "A_DTS": "DTS",
    "A_DTS+dts-x": "DTS:X",
    "A_FLAC": "FLAC",
    "A_OPUS": "Opus",
    "A_VORBIS": "Vorbis",
    "A_MPEG/L3": "MP3",
    "A_MPEG/L2": "MP2",
    "S_TEXT/UTF8": "SubRip",
    "S_TEXT/ASS": "ASS",
    "S_TEXT/SSA": "SSA",
    "S_TEXT/WEBVTT": "WebVTT",
    "S_HDMV/PGS": "PGS",
    "S_VOBSUB": "VobSub",
}

# Keyed by `HdrKind` value; a user rewrites the result through a value map. The probe reports one kind per
# video track and ranks Dolby Vision above its HDR10 base layer, so a Dolby Vision track is named for both.
DEFAULT_HDR_NAMES: dict[str, str] = {
    HdrKind.HDR10.value: "HDR",
    HdrKind.HDR10_PLUS.value: "HDR10+",
    HdrKind.DOLBY_VISION.value: "HDR/DV",
    HdrKind.HLG.value: "HLG",
}

OBJECT_AUDIO_NAMES = {ObjectAudio.ATMOS: "Dolby Atmos", ObjectAudio.DTS_X: "DTS:X"}

_LAYOUTS = {1: "1.0", 2: "2.0", 3: "2.1", 4: "4.0", 5: "5.0", 6: "5.1", 7: "6.1", 8: "7.1"}

# A size reaches a class by width or by height: a widescreen picture cropped to 1920x800 is far below 1080
# lines but still a 1080p source, and a 4:3 picture of 1440x1080 is far below 1920 columns.
_CLASSES = (("2160p", 3200, 1900), ("1080p", 1800, 1000), ("720p", 1200, 700))


def codec_display(codec: str, object_audio: ObjectAudio) -> str:
    """The default table's name, else the raw codec ID."""
    for key in (f"{codec}+{object_audio.value}", codec):
        if key in DEFAULT_CODEC_NAMES:
            return DEFAULT_CODEC_NAMES[key]
    return codec


def hdr_display(hdr: HdrKind) -> str:
    return DEFAULT_HDR_NAMES.get(hdr.value, "")


def resolution(width: int | None, height: int | None) -> str:
    """`2160p`, `1080p`, `720p`, `576p` or `480p`; anything below 720p is standard definition."""
    width, height = width or 0, height or 0
    for name, min_width, min_height in _CLASSES:
        if width >= min_width or height >= min_height:
            return name
    if not height:
        return ""
    return "576p" if height >= 540 else "480p"


def channel_layout(channels: int | None) -> str:
    if not channels:
        return ""
    return _LAYOUTS.get(channels, f"{channels}ch")


# Names are matched between non-alphanumerics, since release names separate words with dots or dashes.
def _marker(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", re.IGNORECASE)


# The order decides: `WEBRip` is tried before `WEB-DL`. A bare `WEB` is not read, because it is also a
# word in titles.
_SOURCES = (
    ("WEBRip", _marker(r"web[ ._-]?rip")),
    ("WEB-DL", _marker(r"web[ ._-]?dl")),
    ("BluRay", _marker(r"blu[ ._-]?ray|bdrip|brrip")),
    ("HDTV", _marker(r"hdtv")),
    ("DVD", _marker(r"dvd(?:rip|r)?")),
)
_HYBRID = _marker("hybrid")
_REMUX = _marker("remux")


def guess_source(release_name: str) -> str:
    """`Hybrid WEB-DL`, `BluRay REMUX` and the like, read from a release name; empty when nothing is found."""
    base = next((name for name, marker in _SOURCES if marker.search(release_name)), "")
    words = ["Hybrid" if _HYBRID.search(release_name) else "", base, "REMUX" if _REMUX.search(release_name) else ""]
    return " ".join(word for word in words if word)


# Release folders carry the tags the file name may lack: `Show Name (2020) [1080p BDRip x265]/Season 1/file.mkv`.
_FOLDER_LEVELS = 3


def guess_source_of(path: Path) -> str:
    """`guess_source` on the file name, then on each parent folder, nearest first, up to three levels."""
    for name in (path.stem, *(parent.name for parent in path.parents[:_FOLDER_LEVELS])):
        if source := guess_source(name):
            return source
    return ""
