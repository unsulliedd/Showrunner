"""`probe`: one `MediaFile` from mkvmerge and ffprobe, or from whichever of them is installed."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from showrunner.core.language import Language
from showrunner.core.media import Attachment, Chapter, ChapterName, MediaFile
from showrunner.core.track import (
    AudioProperties,
    HdrKind,
    SubtitleProperties,
    Track,
    TrackKind,
    VideoProperties,
)
from showrunner.tools.ffmpeg import streams as ff
from showrunner.tools.ffmpeg.ffprobe import FfprobeError, read_first_frames, read_streams
from showrunner.tools.mkvtoolnix.identify import MkvmergeError, identify
from showrunner.tools.probe.matching import codec_id_for, is_text_subtitle, match_streams

DEFAULT_TIMEOUT_SECONDS = 60.0

_KINDS = {"video": TrackKind.VIDEO, "audio": TrackKind.AUDIO, "subtitle": TrackKind.SUBTITLE}


@dataclass(frozen=True, slots=True)
class Programs:
    """Where the programs `probe` can use are; None for one that is not installed."""

    mkvmerge: Path | None = None
    # Without it chapters are not read from an MKV, since only mkvextract gives their names per language.
    mkvextract: Path | None = None
    ffprobe: Path | None = None


class ProbeError(Exception):
    """A file could not be read."""


class MissingProgramsError(ProbeError):
    """Neither program that can read a media file is installed."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        super().__init__(f"cannot read media files without one of: {', '.join(missing)}")
        self.missing = missing  # dependency IDs


@dataclass(frozen=True, slots=True)
class _Run:
    """What one probe needs to call ffprobe again for a single stream."""

    path: Path
    ffprobe: Path | None
    timeout: float
    cancel: threading.Event | None


def probe(
    path: Path,
    programs: Programs,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    cancel: threading.Event | None = None,
) -> MediaFile:
    """Read a file's container, tracks, chapters and attachments.

    mkvmerge is the base because its track IDs are the ones muxing needs. ffprobe adds what mkvmerge does
    not report. Without mkvmerge (or when it cannot read the file) ffprobe alone builds the result with
    `ids_from_mkvmerge` False. Timeouts and cancellation propagate as `ProcessError`.
    """
    if programs.mkvmerge is None and programs.ffprobe is None:
        raise MissingProgramsError(("mkvtoolnix", "ffmpeg"))
    if not path.is_file():
        raise FileNotFoundError(path)
    ctx = _Run(path, programs.ffprobe, timeout, cancel)
    problems: list[str] = []
    base: MediaFile | None = None
    if programs.mkvmerge is not None:
        try:
            base = identify(programs.mkvmerge, path, mkvextract=programs.mkvextract, timeout=timeout, cancel=cancel)
        except MkvmergeError as error:
            problems.append(f"mkvmerge: {error}")
    data: Mapping[str, Any] | None = None
    if programs.ffprobe is not None:
        try:
            data = read_streams(programs.ffprobe, path, timeout=timeout, cancel=cancel)
        except FfprobeError as error:
            problems.append(f"ffprobe: {error}")
    if base is not None:
        return base if data is None else _enrich(base, data, ctx)
    if data is None:
        raise ProbeError(f"{path.name} could not be read ({'; '.join(problems)})")
    return _from_ffprobe(data, ctx)


def _enrich(media: MediaFile, data: Mapping[str, Any], ctx: _Run) -> MediaFile:
    """Add ffprobe's findings to mkvmerge's tracks. A file whose streams do not line up keeps mkvmerge's
    view alone: a wrong HDR kind or channel layout is worse than an unknown one."""
    matched = match_streams(media.tracks, ff.track_streams(data))
    if matched is None:
        return media
    tracks = tuple(_enrich_track(t, s, ctx) for t, s in zip(media.tracks, matched, strict=True))
    return replace(media, tracks=tracks)


def _enrich_track(track: Track, stream: ff.Stream, ctx: _Run) -> Track:
    if track.video is not None:
        video = replace(
            track.video,
            frame_rate=ff.frame_rate(stream) or track.video.frame_rate,
            hdr=_hdr(stream, ctx),
            bit_depth=ff.bit_depth(stream),
        )
        return replace(track, video=video)
    if track.audio is not None:
        return replace(track, audio=replace(track.audio, object_audio=ff.object_audio(stream)))
    return track


def _hdr(stream: ff.Stream, ctx: _Run) -> HdrKind:
    plus = False
    if ctx.ffprobe is not None and ff.needs_dynamic_hdr_check(stream):
        try:
            frames = read_first_frames(
                ctx.ffprobe, ctx.path, int(stream["index"]), timeout=ctx.timeout, cancel=ctx.cancel
            )
            plus = ff.has_hdr10_plus(frames)
        except FfprobeError:
            plus = False  # frames that cannot be read prove nothing, so the file stays HDR10
    return ff.hdr_kind(stream, plus)


def _from_ffprobe(data: Mapping[str, Any], ctx: _Run) -> MediaFile:
    fmt = data.get("format", {})
    all_streams = data.get("streams", ())
    attachments = tuple(
        Attachment(
            id=number,
            file_name=s.get("tags", {}).get("filename", ""),
            mime_type=s.get("tags", {}).get("mimetype", ""),
            size=int(s.get("extradata_size", 0)),
        )
        for number, s in enumerate((s for s in all_streams if s.get("codec_type") == "attachment"), 1)
    )
    chapters = tuple(
        Chapter(
            float(c.get("start_time", 0)),
            float(c["end_time"]) if "end_time" in c else None,
            (ChapterName(None, c["tags"]["title"]),) if c.get("tags", {}).get("title") else (),
        )
        for c in data.get("chapters", ())
    )
    return MediaFile(
        path=ctx.path,
        container=_container_name(fmt),
        duration=float(fmt["duration"]) if "duration" in fmt else None,
        size=int(fmt.get("size", 0)),
        title=fmt.get("tags", {}).get("title", ""),
        tracks=tuple(_track_from_stream(i, s, ctx) for i, s in enumerate(ff.track_streams(data))),
        chapters=chapters,
        attachments=attachments,
        ids_from_mkvmerge=False,
    )


def _container_name(fmt: Mapping[str, Any]) -> str:
    # The name mkvmerge gives, so a file has the same container string whichever program read it.
    name = str(fmt.get("format_name", ""))
    return "Matroska" if name.startswith("matroska") else str(fmt.get("format_long_name", name))


def _track_from_stream(position: int, stream: ff.Stream, ctx: _Run) -> Track:
    kind = _KINDS[stream["codec_type"]]
    tags = stream.get("tags", {})
    code = tags.get("language")
    name = str(stream.get("codec_name", ""))
    video = audio = subtitle = None
    if kind is TrackKind.VIDEO:
        video = VideoProperties(
            stream.get("width"), stream.get("height"), ff.frame_rate(stream), _hdr(stream, ctx), ff.bit_depth(stream)
        )
    elif kind is TrackKind.AUDIO:
        rate = stream.get("sample_rate")
        audio = AudioProperties(stream.get("channels"), int(rate) if rate else None, ff.object_audio(stream))
    else:
        subtitle = SubtitleProperties(is_text_subtitle(name))
    return Track(
        id=position,
        kind=kind,
        codec=codec_id_for(name),
        language=Language.parse(code) if code else None,
        name=tags.get("title", ""),
        flags=ff.disposition_flags(stream),
        video=video,
        audio=audio,
        subtitle=subtitle,
    )
