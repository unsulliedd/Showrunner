"""What was read from each video, kept in the data folder so opening the same folders again reads only what changed.

An entry is served only while the file's size, modification time and the programs that read it are the ones it
was stored with; anything else reads the file again. A file that could not be read gets no entry, so it is tried
again next time, when a program may have been installed since.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from showrunner.app.storage.files import write_json_atomic
from showrunner.core.language import Language
from showrunner.core.media import Attachment, Chapter, ChapterName, MediaFile, MediaItem
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
from showrunner.stages.scan.probing import Reader
from showrunner.tools.probe import Programs

_log = logging.getLogger(__name__)

# Raised whenever the stored shape of a media file changes, so no entry is read back into a shape it was not made for.
FORMAT_VERSION = 2

type Entries = dict[str, Any]  # by the file's resolved path


def load_cache(path: Path) -> Entries:
    """The stored entries. A missing file gives none silently; an unreadable one or one of another format gives
    none and a log line, and is built again."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _log.warning("The read cache %s could not be read and is built again", path)
        return {}
    if not isinstance(data, dict) or data.get("format") != FORMAT_VERSION or not isinstance(data.get("entries"), dict):
        _log.info("The read cache %s has another format and is built again", path)
        return {}
    return data["entries"]


def save_cache(path: Path, entries: Entries) -> None:
    """Write the entries; a failure costs only the next start's speed, so it is logged and not raised."""
    try:
        write_json_atomic(path, {"format": FORMAT_VERSION, "entries": entries})
    except OSError:
        _log.exception("Could not save the read cache")


class CachedReader:
    """`read` with the cache in front of it. It changes `entries` as it reads; `changed` says whether to save them."""

    def __init__(self, read: Reader, entries: Entries) -> None:
        self._read = read
        self.entries = entries
        self.changed = False

    def drop_gone(self, folders: Iterable[Path], scanned: Iterable[MediaItem]) -> None:
        """Forget the files inside the scanned folders that the scan no longer found. Files elsewhere are left
        alone: their folders were not looked at."""
        folders = tuple(f.resolve() for f in folders)
        seen = {str(i.file.path.resolve()) for i in scanned}
        gone = [k for k in self.entries if k not in seen and any(Path(k).is_relative_to(f) for f in folders)]
        for key in gone:
            del self.entries[key]
        self.changed |= bool(gone)

    def __call__(self, path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        key = str(path.resolve())
        # Taken before the read, so a write while it runs leaves a stamp that no longer matches the file.
        stat = path.stat()
        stamp = {"size": stat.st_size, "modified_ns": stat.st_mtime_ns, "readers": _readers(programs)}
        entry = self.entries.get(key)
        if isinstance(entry, dict) and all(entry.get(name) == value for name, value in stamp.items()):
            try:
                return media_from_json(path, entry["file"])
            except (KeyError, TypeError, ValueError, AttributeError):
                _log.warning("The read cache entry of %s could not be read back; the file is read again", path)
        if self.entries.pop(key, None) is not None:
            self.changed = True
        file = self._read(path, programs, cancel=cancel)
        self.entries[key] = {**stamp, "file": media_to_json(file)}
        self.changed = True
        return file


def _readers(programs: Programs) -> dict[str, str | None]:
    # Each program adds what the others miss (ffprobe the HDR kind, mkvextract the chapter names), so a program
    # installed, removed or moved since makes the entry stale.
    return {name: None if found is None else str(found) for name, found in asdict(programs).items()}


def media_to_json(file: MediaFile) -> dict[str, Any]:
    """Everything read from the file but its path, which the entry is keyed by."""
    data = asdict(file)
    del data["path"]
    return data


def media_from_json(path: Path, data: dict[str, Any]) -> MediaFile:
    return MediaFile(
        **{
            **data,
            "path": path,
            "tracks": tuple(_track(t) for t in data["tracks"]),
            "chapters": tuple(
                Chapter(
                    c["start"], c["end"], tuple(ChapterName(_language(n["language"]), n["text"]) for n in c["names"])
                )
                for c in data["chapters"]
            ),
            "attachments": tuple(Attachment(**a) for a in data["attachments"]),
        }
    )


def _track(data: dict[str, Any]) -> Track:
    video, audio, subtitle = data["video"], data["audio"], data["subtitle"]
    return Track(
        **{
            **data,
            "kind": TrackKind(data["kind"]),
            "language": _language(data["language"]),
            "flags": TrackFlags(**data["flags"]),
            "video": None if video is None else VideoProperties(**{**video, "hdr": HdrKind(video["hdr"])}),
            "audio": None
            if audio is None
            else AudioProperties(**{**audio, "object_audio": ObjectAudio(audio["object_audio"])}),
            "subtitle": None if subtitle is None else SubtitleProperties(**subtitle),
        }
    )


def _language(data: dict[str, Any] | None) -> Language | None:
    return None if data is None else Language(**data)
