"""The library as the window shows it: scanned and probed items, plus every manual change to their pairing."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import IntEnum
from pathlib import Path

from showrunner.core.media import Episode, MediaItem, Movie, SubtitleFile
from showrunner.stages.scan import Alternatives, ProbeFailure, attach, detach, move_subtitle
from showrunner.stages.scan.scanner import natural_key


class Mark(IntEnum):
    """What a row needs from the user; a higher value is worse, so a parent shows the maximum of its rows."""

    NONE = 0
    UNSURE = 1  # the scan found more than one subtitle file that fits
    FAILED = 2  # the file could not be read


@dataclass(frozen=True, slots=True)
class Counts:
    videos: int = 0
    shows: int = 0
    episodes: int = 0
    movies: int = 0
    unsure: int = 0  # videos with a pairing the scan was unsure of
    failed: int = 0
    unpaired: int = 0
    needs_look: int = 0  # videos with either mark, each counted once


@dataclass(frozen=True, slots=True)
class LibraryLoad:
    """What one load found: only the videos that were not in the library before."""

    items: tuple[MediaItem, ...] = ()
    alternatives: tuple[Alternatives, ...] = ()
    unpaired: tuple[SubtitleFile, ...] = ()
    failures: tuple[ProbeFailure, ...] = ()
    cancelled: bool = False
    roots: tuple[Path, ...] = ()  # the folders that were dropped


def _variant(subtitle: SubtitleFile) -> tuple:
    return subtitle.language, subtitle.forced, subtitle.sdh


@dataclass(frozen=True, slots=True)
class Library:
    items: tuple[MediaItem, ...] = ()
    alternatives: tuple[Alternatives, ...] = ()
    unpaired: tuple[SubtitleFile, ...] = ()
    failures: tuple[ProbeFailure, ...] = ()
    roots: tuple[Path, ...] = ()

    def relative_path(self, path: Path) -> Path:
        """The path below the folder that was dropped, starting with that folder's name; a file that was
        dropped by itself has only its name."""
        root = next((r for r in self.roots if path.is_relative_to(r)), None)
        return path.relative_to(root.parent) if root is not None else Path(path.name)

    def item(self, path: Path) -> MediaItem | None:
        return next((i for i in self.items if i.file.path == path), None)

    def failure(self, path: Path) -> str | None:
        return next((f.reason for f in self.failures if f.path == path), None)

    def alternatives_of(self, path: Path) -> tuple[SubtitleFile, ...]:
        return tuple(s for a in self.alternatives if a.video == path for s in a.subtitles)

    def mark(self, path: Path) -> Mark:
        if self.failure(path) is not None:
            return Mark.FAILED
        return Mark.UNSURE if any(a.video == path for a in self.alternatives) else Mark.NONE

    def unpaired_near(self, videos: Iterable[Path]) -> tuple[SubtitleFile, ...]:
        """Unpaired subtitle files in the folder of any of the videos, or in a `Subs` folder inside it."""
        folders = {v.parent for v in videos}
        return tuple(s for s in self.unpaired if s.path.parent in folders or s.path.parent.parent in folders)

    def counts(self, paths: Iterable[Path] | None = None) -> Counts:
        """The counts of the whole library, or of the videos at `paths` and the unpaired files beside them."""
        wanted = None if paths is None else set(paths)
        items = [i for i in self.items if wanted is None or i.file.path in wanted]
        marks = [self.mark(i.file.path) for i in items]
        unpaired = self.unpaired if wanted is None else self.unpaired_near(i.file.path for i in items)
        episodes = [i.identity for i in items if isinstance(i.identity, Episode)]
        return Counts(
            videos=len(items),
            shows=len({e.show.casefold() for e in episodes}),
            episodes=len(episodes),
            movies=sum(isinstance(i.identity, Movie) for i in items),
            unsure=marks.count(Mark.UNSURE),
            failed=marks.count(Mark.FAILED),
            unpaired=len(unpaired),
            needs_look=sum(m is not Mark.NONE for m in marks),
        )

    def merge(self, load: LibraryLoad) -> Library:
        """The library with a load added. A subtitle file already attached or listed is not listed again."""
        known = {s.path for i in self.items for s in i.subtitles} | {s.path for s in self.unpaired}
        fresh = tuple(s for s in load.unpaired if s.path not in known)
        return Library(
            tuple(sorted((*self.items, *load.items), key=lambda i: natural_key(i.file.path))),
            (*self.alternatives, *load.alternatives),
            tuple(sorted((*self.unpaired, *fresh), key=lambda s: natural_key(s.path))),
            (*self.failures, *load.failures),
            tuple(dict.fromkeys((*self.roots, *load.roots))),
        )

    def pair(self, subtitle: SubtitleFile, video: Path) -> Library:
        """Give an unpaired file to a video."""
        items = move_subtitle(self.items, subtitle, video)
        return replace(self, items=items, unpaired=tuple(s for s in self.unpaired if s.path != subtitle.path))

    def unpair(self, subtitle: SubtitleFile) -> Library:
        """Take a file from its video; it is listed as unpaired afterwards."""
        items = move_subtitle(self.items, subtitle, None)
        unpaired = sorted((*self.unpaired, subtitle), key=lambda s: natural_key(s.path))
        return replace(self, items=items, unpaired=tuple(unpaired))

    def pair_instead(self, video: Path, subtitle: SubtitleFile) -> Library:
        """Pair one of the alternatives with the video in place of the file of the same language and kind.

        That decides the doubt: the replaced file and the other alternatives become unpaired and the video is
        no longer marked unsure."""
        group = next((a for a in self.alternatives if a.video == video and subtitle in a.subtitles), None)
        item = self.item(video)
        if group is None or item is None:
            return self
        replaced = tuple(s for s in item.subtitles if _variant(s) == _variant(subtitle))
        updated = item
        for old in replaced:
            updated = detach(updated, old.path)
        updated = attach(updated, subtitle)
        left = (*replaced, *(s for s in group.subtitles if s != subtitle))
        return Library(
            tuple(updated if i.file.path == video else i for i in self.items),
            tuple(a for a in self.alternatives if a is not group),
            tuple(sorted((*self.unpaired, *left), key=lambda s: natural_key(s.path))),
            self.failures,
            self.roots,
        )
