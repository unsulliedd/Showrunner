"""Tracks of a media file and their properties."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    text_based: bool = True


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
