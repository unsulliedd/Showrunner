"""Turning media values into the short texts the sheet shows."""

from __future__ import annotations

from pathlib import Path

from showrunner.app.library.library import Counts
from showrunner.core.language import Language
from showrunner.core.media import Episode, Extra, MediaItem, Movie
from showrunner.core.track import HdrKind, ObjectAudio, Track, TrackKind
from showrunner.ui.i18n.catalog import tr, tr_plural

SEPARATOR = " · "

# Codec IDs as mkvmerge reports them. A codec missing here is shown as the program reports it.
_CODEC_NAMES = {
    "V_MPEGH/ISO/HEVC": "HEVC",
    "V_MPEG4/ISO/AVC": "AVC",
    "V_MPEG2": "MPEG-2",
    "V_AV1": "AV1",
    "V_VP9": "VP9",
    "A_AAC": "AAC",
    "A_AC3": "AC-3",
    "A_EAC3": "E-AC-3",
    "A_TRUEHD": "TrueHD",
    "A_DTS": "DTS",
    "A_FLAC": "FLAC",
    "A_OPUS": "Opus",
    "A_VORBIS": "Vorbis",
    "A_MPEG/L3": "MP3",
    "S_TEXT/UTF8": "SubRip",
    "S_TEXT/ASS": "ASS",
    "S_TEXT/SSA": "SSA",
    "S_TEXT/WEBVTT": "WebVTT",
    "S_HDMV/PGS": "PGS",
    "S_VOBSUB": "VobSub",
}

_SUBTITLE_FORMATS = {
    ".srt": "SubRip",
    ".ass": "ASS",
    ".ssa": "SSA",
    ".vtt": "WebVTT",
    ".sub": "VobSub",
    ".idx": "VobSub",
    ".sup": "PGS",
}

_HDR = {HdrKind.HDR10: "HDR10", HdrKind.HDR10_PLUS: "HDR10+", HdrKind.DOLBY_VISION: "DV", HdrKind.HLG: "HLG"}
_OBJECT_AUDIO = {ObjectAudio.ATMOS: "Atmos", ObjectAudio.DTS_X: "DTS:X"}
_LAYOUTS = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}

_KB = 1000
_UNITS = (("common.size_gb", _KB**3), ("common.size_mb", _KB**2), ("common.size_kb", _KB))


def codec_name(codec: str) -> str:
    return _CODEC_NAMES.get(codec, codec)


def language_code(language: Language | None) -> str:
    return language.alpha3 if language else tr("common.none")


def subtitle_format(path: Path) -> str:
    return _SUBTITLE_FORMATS.get(path.suffix.lower(), path.suffix.lstrip(".").upper())


def size_text(size: int) -> str:
    for key, unit in _UNITS:
        if size >= unit:
            return tr(key, value=f"{size / unit:.2f}" if unit == _KB**3 else f"{size / unit:.0f}")
    return tr("common.size_b", value=size)


def duration_text(seconds: float) -> str:
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def track_summary(track: Track) -> str:
    """One line of what matters for the kind of track."""
    parts = [codec_name(track.codec)]
    if track.kind is TrackKind.VIDEO and track.video is not None:
        video = track.video
        if video.height:
            parts.append(f"{video.height}p")
        if video.hdr in _HDR:
            parts.append(_HDR[video.hdr])
        if video.bit_depth:
            parts.append(tr("sheet.bit_depth", value=video.bit_depth))
        if video.frame_rate:
            parts.append(tr("sheet.frame_rate", value=f"{video.frame_rate:.3f}".rstrip("0").rstrip(".")))
    elif track.kind is TrackKind.AUDIO and track.audio is not None:
        audio = track.audio
        if audio.channels:
            parts.append(_LAYOUTS.get(audio.channels, tr("sheet.channels", count=audio.channels)))
        if audio.object_audio in _OBJECT_AUDIO:
            parts.append(_OBJECT_AUDIO[audio.object_audio])
    elif track.kind is TrackKind.SUBTITLE and track.subtitle is not None:
        parts.append(tr("sheet.subtitle_text" if track.subtitle.text_based else "sheet.subtitle_image"))
    return SEPARATOR.join(parts)


def item_title(item: MediaItem) -> str:
    identity = item.identity
    if isinstance(identity, Movie):
        return movie_name(identity)
    if isinstance(identity, Extra):
        return tr("sheet.title.extra", show=identity.show, title=identity.title)
    name = identity.episode_title
    code = tr("sheet.episode_code", season=identity.season, episode=identity.episode)
    return tr("sheet.title.episode", show=identity.show, code=code, title=name) if name else f"{identity.show} {code}"


def movie_name(movie: Movie) -> str:
    return tr("library.movie", title=movie.title, year=movie.year) if movie.year else movie.title


def episode_name(episode: Episode) -> str:
    return tr("library.episode", number=episode.episode, title=episode.episode_title).rstrip()


def count_parts(counts: Counts, *, breakdown: bool = True) -> list[tuple[str, str]]:
    """The summary of a set of videos as (text, role) parts; a part that is a problem carries its mark's role.

    Problems with a count of zero are left out.
    """
    parts = [(tr_plural("summary.videos", counts.videos), "")]
    if breakdown and counts.videos:
        kinds = [
            tr_plural(f"summary.{kind}", n)
            for kind, n in (
                ("shows", counts.shows),
                ("episodes", counts.episodes),
                ("extras", counts.extras),
                ("movies", counts.movies),
            )
            if n
        ]
        parts.append((tr("common.list_separator").join(kinds), ""))
    if counts.unsure:
        parts.append((tr_plural("summary.unsure", counts.unsure), "notice"))
    if counts.failed:
        parts.append((tr_plural("summary.failed", counts.failed), "danger"))
    if counts.unpaired:
        parts.append((tr_plural("summary.unpaired", counts.unpaired), ""))
    return parts
