"""Reading what ffprobe reports about streams: HDR kind, bit depth, frame rate, object audio, flags."""

from __future__ import annotations

import re
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from showrunner.core.track import HdrKind, ObjectAudio, TrackFlags

Stream = Mapping[str, Any]

_PQ = "smpte2084"
_HLG = "arib-std-b67"
_TRACK_TYPES = ("video", "audio", "subtitle")
_DEPTH = re.compile(r"(\d+)(?:le|be)$")


def track_streams(data: Mapping[str, Any]) -> list[Stream]:
    """The streams that are tracks, in file order: no attachments, data streams or cover pictures."""
    return [
        s
        for s in data.get("streams", ())
        if s.get("codec_type") in _TRACK_TYPES and not s.get("disposition", {}).get("attached_pic")
    ]


def has_dolby_vision(stream: Stream) -> bool:
    """The stream carries a Dolby Vision configuration record (profile, level and compatibility)."""
    return any("DOVI" in str(side.get("side_data_type", "")) for side in stream.get("side_data_list", ()))


def needs_dynamic_hdr_check(stream: Stream) -> bool:
    """HDR10+ can only sit on a PQ stream, and a Dolby Vision stream is classified without looking further.

    This keeps the frame read, which decodes video, off every ordinary file.
    """
    return stream.get("color_transfer") == _PQ and not has_dolby_vision(stream)


def has_hdr10_plus(frames: Mapping[str, Any]) -> bool:
    """Any of the listed frames carries SMPTE ST 2094-40 dynamic metadata."""
    return any(
        "2094-40" in str(side.get("side_data_type", "")) or "HDR10+" in str(side.get("side_data_type", ""))
        for frame in frames.get("frames", ())
        for side in frame.get("side_data_list", ())
    )


def hdr_kind(stream: Stream, hdr10_plus: bool = False) -> HdrKind:
    """Dolby Vision wins over HDR10+ and HDR10: a file with Dolby Vision on top of an HDR10 base layer is
    named for the better format, and the app keeps one kind per track."""
    if has_dolby_vision(stream):
        return HdrKind.DOLBY_VISION
    transfer = stream.get("color_transfer")
    if transfer == _PQ:
        return HdrKind.HDR10_PLUS if hdr10_plus else HdrKind.HDR10
    if transfer == _HLG:
        return HdrKind.HLG
    return HdrKind.NONE


def bit_depth(stream: Stream) -> int | None:
    raw = stream.get("bits_per_raw_sample")
    if raw and str(raw).isdigit() and int(raw) > 0:
        return int(raw)
    pix_fmt = str(stream.get("pix_fmt", ""))
    if not pix_fmt:
        return None
    # `yuv420p10le`, `p010le`: the depth sits before the byte order; formats without a byte order are 8-bit.
    match = _DEPTH.search(pix_fmt)
    return int(match[1]) if match and 9 <= int(match[1]) <= 16 else 8


def frame_rate(stream: Stream) -> float | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            rate = Fraction(stream.get(key) or "0/0")
        except (ZeroDivisionError, ValueError):
            continue
        if rate > 0:
            return float(rate)
    return None


def object_audio(stream: Stream) -> ObjectAudio:
    """Atmos and DTS:X ride inside TrueHD, E-AC-3 and DTS streams; ffprobe names them in the profile."""
    profile = str(stream.get("profile", "")).lower()
    codec = stream.get("codec_name")
    if codec in ("truehd", "eac3") and "atmos" in profile:
        return ObjectAudio.ATMOS
    if codec == "dts" and "dts:x" in profile:
        return ObjectAudio.DTS_X
    return ObjectAudio.NONE


def disposition_flags(stream: Stream) -> TrackFlags:
    d = stream.get("disposition", {})
    return TrackFlags(
        default=bool(d.get("default")),
        forced=bool(d.get("forced")),
        hearing_impaired=bool(d.get("hearing_impaired")),
        visual_impaired=bool(d.get("visual_impaired")),
        commentary=bool(d.get("comment")),
        original=bool(d.get("original")),
    )
