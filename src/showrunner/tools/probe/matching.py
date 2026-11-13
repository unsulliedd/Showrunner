"""Pairing mkvmerge's tracks with ffprobe's streams, and the codec naming both sides share."""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatchcase

from showrunner.core.track import Track, TrackKind
from showrunner.tools.ffmpeg.streams import Stream

# Matroska codec ID prefix and the ffprobe codec names that go with it. The Matroska ID is the codec string
# of a track: it is fixed by the Matroska specification, while mkvmerge's display names ("TrueHD",
# "HEVC/H.265/MPEG-H") are free text that changes between releases. ffprobe does not report Matroska IDs, so
# this table is also how a track read from ffprobe alone gets one (the first line that lists its name).
_CODECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("V_MPEGH/ISO/HEVC", ("hevc",)),
    ("V_MPEG4/ISO/AVC", ("h264",)),
    ("V_MPEG4/ISO", ("mpeg4",)),
    ("V_MPEG2", ("mpeg2video",)),
    ("V_MPEG1", ("mpeg1video",)),
    ("V_MPEGI/ISO/VVC", ("vvc",)),
    ("V_VP8", ("vp8",)),
    ("V_VP9", ("vp9",)),
    ("V_AV1", ("av1",)),
    ("A_AAC", ("aac",)),
    ("A_AC3", ("ac3",)),
    ("A_EAC3", ("eac3",)),
    ("A_TRUEHD", ("truehd",)),
    ("A_MLP", ("mlp",)),
    ("A_DTS", ("dts",)),
    ("A_OPUS", ("opus",)),
    ("A_VORBIS", ("vorbis",)),
    ("A_FLAC", ("flac",)),
    ("A_ALAC", ("alac",)),
    ("A_MPEG/L3", ("mp3",)),
    ("A_MPEG/L2", ("mp2",)),
    ("A_PCM", ("pcm_*",)),
    ("S_TEXT/UTF8", ("subrip", "text")),
    ("S_TEXT/ASS", ("ass",)),
    ("S_TEXT/SSA", ("ssa", "ass")),
    ("S_TEXT/WEBVTT", ("webvtt",)),
    ("S_HDMV/PGS", ("hdmv_pgs_subtitle",)),
    ("S_HDMV/TEXTST", ("hdmv_text_subtitle",)),
    ("S_VOBSUB", ("dvd_subtitle",)),
    ("S_DVBSUB", ("dvb_subtitle",)),
)

_IMAGE_SUBTITLES = frozenset({"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"})
_KIND_OF_TYPE = {"video": TrackKind.VIDEO, "audio": TrackKind.AUDIO, "subtitle": TrackKind.SUBTITLE}


def codec_id_for(codec_name: str) -> str:
    """The Matroska codec ID for an ffprobe codec name; a name not in the table is kept as ffprobe wrote it."""
    for prefix, names in _CODECS:
        if any(fnmatchcase(codec_name, pattern) for pattern in names):
            return prefix
    return codec_name


def is_text_subtitle(codec_name: str) -> bool:
    return codec_name not in _IMAGE_SUBTITLES


def match_streams(tracks: Sequence[Track], streams: Sequence[Stream]) -> list[Stream] | None:
    """The stream of each track, or None when the two lists cannot be trusted to line up.

    Tracks and streams are paired by position, since both programs list a file's tracks in file order.
    Position alone could pair the wrong two tracks when a container is ordered differently by the two
    programs (transport streams), so every pair must also agree on its kind and codec and, where both
    sides report them, on the picture size and the channel count. One bad pair rejects the whole list: a
    shifted order makes every later pair suspect.
    """
    if len(tracks) != len(streams):
        return None
    return list(streams) if all(_agrees(track, stream) for track, stream in zip(tracks, streams, strict=True)) else None


def _agrees(track: Track, stream: Stream) -> bool:
    if _KIND_OF_TYPE.get(stream.get("codec_type", "")) is not track.kind:
        return False
    if not _codec_agrees(track.codec, str(stream.get("codec_name", ""))):
        return False
    if track.video and track.video.width and track.video.height and stream.get("width"):
        return (track.video.width, track.video.height) == (stream["width"], stream.get("height"))
    if track.audio and track.audio.channels and stream.get("channels"):
        return track.audio.channels == stream["channels"]
    return True


def _codec_agrees(codec_id: str, codec_name: str) -> bool:
    """An ID the table does not know cannot be judged and is let through; the other checks still apply."""
    for prefix, names in _CODECS:
        if codec_id.startswith(prefix):
            return any(fnmatchcase(codec_name, pattern) for pattern in names)
    return True
