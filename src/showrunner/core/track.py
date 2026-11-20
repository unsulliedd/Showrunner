"""Tracks of a media file and their properties."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum

from showrunner.core.language import Language


class TrackKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


class HdrKind(StrEnum):
    NONE = "none"
    HDR10 = "hdr10"
    HDR10_PLUS = "hdr10+"
    DOLBY_VISION = "dolby-vision"
    HLG = "hlg"


class ObjectAudio(StrEnum):
    NONE = "none"
    ATMOS = "atmos"
    DTS_X = "dts-x"


@dataclass(frozen=True, slots=True)
class TrackFlags:
    default: bool = False
    forced: bool = False
    hearing_impaired: bool = False
    visual_impaired: bool = False
    commentary: bool = False
    original: bool = False


@dataclass(frozen=True, slots=True)
class VideoProperties:
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    hdr: HdrKind = HdrKind.NONE
    bit_depth: int | None = None


@dataclass(frozen=True, slots=True)
class AudioProperties:
    channels: int | None = None
    sample_rate: int | None = None
    object_audio: ObjectAudio = ObjectAudio.NONE


@dataclass(frozen=True, slots=True)
class SubtitleProperties:
    text_based: bool = True  # not read yet; the subtitle stage skips image subtitles by it


@dataclass(frozen=True, slots=True)
class Track:
    """One track. Exactly the property group of its kind may be set (it stays None when unknown).

    One class with optional groups, not a subclass per kind: selection rules, the track table and
    the muxer treat all tracks alike and read the shared fields without a type check, and
    `dataclasses.replace` copies any track the same way.
    """

    id: int  # mkvmerge track ID, the number used on mkvmerge command lines
    kind: TrackKind
    codec: str = ""  # as the tool reports it
    language: Language | None = None
    name: str = ""
    flags: TrackFlags = field(default_factory=TrackFlags)
    video: VideoProperties | None = None
    audio: AudioProperties | None = None
    subtitle: SubtitleProperties | None = None

    def __post_init__(self) -> None:
        groups = {TrackKind.VIDEO: self.video, TrackKind.AUDIO: self.audio, TrackKind.SUBTITLE: self.subtitle}
        for kind, group in groups.items():
            if kind is not self.kind and group is not None:
                raise ValueError(f"{kind.value} properties set on a track of kind {self.kind.value}")


# Words in a track name that mark a flag many files leave unset, such as a commentary track named
# "Commentary by the director" without the commentary flag.
_FLAGS_IN_NAMES = (
    ("commentary", re.compile(r"\b(?:commentary|commentaire|kommentar|comentario|commento)\b", re.IGNORECASE)),
    ("hearing_impaired", re.compile(r"\b(?:sdh|cc|hearing[ -]impaired)\b", re.IGNORECASE)),
    ("forced", re.compile(r"\bforced\b", re.IGNORECASE)),
)


def flags_with_name(track: Track) -> TrackFlags:
    """The track's flags, plus the commentary, hearing impaired and forced flags its name implies."""
    implied = {flag: True for flag, pattern in _FLAGS_IN_NAMES if pattern.search(track.name)}
    return replace(track.flags, **implied) if implied else track.flags
