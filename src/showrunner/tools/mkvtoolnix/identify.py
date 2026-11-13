"""`mkvmerge -J`: the container, its tracks, attachments and whether it has chapters."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from showrunner.core.language import Language
from showrunner.core.media import Attachment, MediaFile
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackFlags, TrackKind, VideoProperties
from showrunner.tools.mkvtoolnix.chapters import extract_chapters
from showrunner.tools.process import run

_KINDS = {"video": TrackKind.VIDEO, "audio": TrackKind.AUDIO, "subtitles": TrackKind.SUBTITLE}
_DIMENSIONS = re.compile(r"(\d+)x(\d+)")


class MkvmergeError(Exception):
    """mkvmerge could not read the file or wrote output that is not an identification."""


def identify(
    mkvmerge: Path,
    path: Path,
    *,
    mkvextract: Path | None = None,
    timeout: float,
    cancel: threading.Event | None = None,
) -> MediaFile:
    """Read a file with `mkvmerge -J`; chapters are read with `mkvextract` when the file has any."""
    # Exit code 1 means warnings only; 2 means the file could not be read.
    result = run([mkvmerge, "-J", path], timeout=timeout, cancel=cancel)
    try:
        data = json.loads(result.stdout)
    except ValueError as error:
        raise MkvmergeError(result.stderr.strip() or f"no identification (exit code {result.returncode})") from error
    if result.returncode >= 2 or not data.get("container", {}).get("supported", False):
        errors = data.get("errors") or [f"exit code {result.returncode}"]
        raise MkvmergeError("; ".join(str(e) for e in errors))
    media = parse_identification(data, path)
    if mkvextract is not None and has_chapters(data):
        media = replace(media, chapters=extract_chapters(mkvextract, path, timeout=timeout, cancel=cancel))
    return media


def has_chapters(data: Mapping[str, Any]) -> bool:
    return any(entry.get("num_entries", 0) > 0 for entry in data.get("chapters", ()))


def parse_identification(data: Mapping[str, Any], path: Path) -> MediaFile:
    container = data.get("container", {})
    props = container.get("properties", {})
    nanoseconds = props.get("duration")
    tracks = [t for raw in data.get("tracks", ()) if (t := _track(raw)) is not None]
    return MediaFile(
        path=path,
        container=container.get("type", ""),
        duration=None if nanoseconds is None else nanoseconds / 1e9,
        size=path.stat().st_size if path.is_file() else 0,
        title=props.get("title", ""),
        tracks=tuple(tracks),
        attachments=tuple(_attachment(a) for a in data.get("attachments", ())),
    )


def _track(raw: Mapping[str, Any]) -> Track | None:
    kind = _KINDS.get(raw.get("type", ""))
    if kind is None:  # button tracks of DVDs carry nothing the app uses
        return None
    p = raw.get("properties", {})
    return Track(
        id=raw["id"],
        kind=kind,
        codec=p.get("codec_id") or raw.get("codec", ""),
        language=_language(p),
        name=p.get("track_name", ""),
        flags=TrackFlags(
            default=bool(p.get("default_track")),
            forced=bool(p.get("forced_track")),
            hearing_impaired=bool(p.get("flag_hearing_impaired")),
            visual_impaired=bool(p.get("flag_visual_impaired")),
            commentary=bool(p.get("flag_commentary")),
            original=bool(p.get("flag_original")),
        ),
        video=_video(p) if kind is TrackKind.VIDEO else None,
        audio=_audio(p) if kind is TrackKind.AUDIO else None,
        subtitle=SubtitleProperties(text_based=bool(p.get("text_subtitles"))) if kind is TrackKind.SUBTITLE else None,
    )


def _language(p: Mapping[str, Any]) -> Language | None:
    # `language_ietf` carries region and script (`pt-BR`); `language` is the legacy three-letter code.
    code = p.get("language_ietf") or p.get("language")
    return Language.parse(code) if code else None


def _video(p: Mapping[str, Any]) -> VideoProperties:
    size = _DIMENSIONS.fullmatch(p.get("pixel_dimensions", ""))
    nanoseconds = p.get("default_duration")
    return VideoProperties(
        width=int(size[1]) if size else None,
        height=int(size[2]) if size else None,
        frame_rate=1e9 / nanoseconds if nanoseconds else None,
    )


def _audio(p: Mapping[str, Any]) -> AudioProperties:
    return AudioProperties(channels=p.get("audio_channels"), sample_rate=p.get("audio_sampling_frequency"))


def _attachment(raw: Mapping[str, Any]) -> Attachment:
    return Attachment(
        id=raw["id"],
        file_name=raw.get("file_name", ""),
        mime_type=raw.get("content_type", ""),
        size=raw.get("size", 0),
        description=raw.get("description", ""),
    )
