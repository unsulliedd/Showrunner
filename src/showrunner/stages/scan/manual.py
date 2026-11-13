"""Pairing by hand: each function returns new items and leaves the given ones untouched."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from showrunner.core.media import MediaItem, SubtitleFile


def attach(item: MediaItem, subtitle: SubtitleFile) -> MediaItem:
    """The item with the subtitle file added; a file already attached under the same path is replaced."""
    others = tuple(s for s in item.subtitles if s.path != subtitle.path)
    return replace(item, subtitles=(*others, subtitle))


def detach(item: MediaItem, subtitle_path: Path) -> MediaItem:
    return replace(item, subtitles=tuple(s for s in item.subtitles if s.path != subtitle_path))


def move_subtitle(items: Iterable[MediaItem], subtitle: SubtitleFile, video: Path | None) -> tuple[MediaItem, ...]:
    """Give the file to the item of `video` and take it from every other item; None only takes it away."""
    return tuple(
        attach(detached, subtitle) if detached.file.path == video else detached
        for detached in (detach(item, subtitle.path) for item in items)
    )
