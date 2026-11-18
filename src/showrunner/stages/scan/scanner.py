"""Scanning dropped folders and files into media items with their subtitle files."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from showrunner.core.media import MediaFile, MediaItem, SubtitleFile
from showrunner.stages.scan.extensions import SUBTITLE_EXTENSIONS, SUBTITLE_FOLDER_NAMES, VIDEO_EXTENSIONS
from showrunner.stages.scan.identify import holds_show, identify
from showrunner.stages.scan.names import parse_subtitle_name, spaced
from showrunner.stages.scan.options import ScanOptions
from showrunner.stages.scan.pairing import name_keys, pair
from showrunner.stages.scan.subtitles import read_subtitle
from showrunner.stages.scan.walk import walk_files


@dataclass(frozen=True, slots=True)
class Alternatives:
    """Other subtitle files that fit a video as well as the attached one; the user picks."""

    video: Path
    subtitles: tuple[SubtitleFile, ...]


@dataclass(frozen=True, slots=True)
class ScanResult:
    items: tuple[MediaItem, ...] = ()
    alternatives: tuple[Alternatives, ...] = ()
    unpaired: tuple[SubtitleFile, ...] = ()  # fit no video, or only a video that took another file


def natural_key(path: Path) -> list[str | int]:
    """Sort key that puts `Season 2` before `Season 10`."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(path))]


def _is_subtitle_folder(folder: Path) -> bool:
    return folder.name.casefold() in SUBTITLE_FOLDER_NAMES


def _neighbour_subtitles(video: Path, options: ScanOptions) -> Iterator[Path]:
    """Subtitle files in the folder of a dropped video and in its `Subs` folder."""
    folders = [video.parent]
    if options.subtitle_subfolders:
        folders += [d for d in sorted(video.parent.iterdir()) if d.is_dir() and _is_subtitle_folder(d)]
    for folder in folders:
        yield from (p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in SUBTITLE_EXTENSIONS)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def scan(paths: Iterable[Path], options: ScanOptions | None = None) -> ScanResult:
    """Find the videos below the paths, identify each and pair the subtitle files found beside them."""
    options = options or ScanOptions()
    roots = [Path(p) for p in paths]
    videos: dict[Path, list[Path]] = {}
    subtitles: dict[Path, list[Path]] = {}
    known: set[Path] = set()

    def add_subtitle(path: Path) -> None:
        known.add(path)
        folder = path.parent
        if options.subtitle_subfolders and _is_subtitle_folder(folder):
            folder = folder.parent
        subtitles.setdefault(folder, []).append(path)

    for path in walk_files(roots):
        suffix = path.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            videos.setdefault(path.parent, []).append(path)
        elif suffix in SUBTITLE_EXTENSIONS:
            add_subtitle(path)

    # Subtitle files that only came along with a dropped video are matched, but not reported when they fit none:
    # they most likely belong to videos that were not dropped.
    incidental: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix.lower() in VIDEO_EXTENSIONS:
            for neighbour in _neighbour_subtitles(root, options):
                if neighbour not in known:
                    add_subtitle(neighbour)
                    incidental.add(neighbour)

    shows = cache(holds_show)  # one look at each folder, however many videos lie in it
    items: list[MediaItem] = []
    alternatives: list[Alternatives] = []
    unpaired: list[SubtitleFile] = []
    for folder in videos.keys() | subtitles.keys():
        folder_items, folder_alternatives, folder_unpaired = _scan_folder(
            sorted(videos.get(folder, []), key=natural_key),
            sorted(subtitles.get(folder, []), key=natural_key),
            options,
            shows,
        )
        items += folder_items
        alternatives += folder_alternatives
        unpaired += (s for s in folder_unpaired if s.path not in incidental)
    return ScanResult(
        tuple(sorted(items, key=lambda i: natural_key(i.file.path))),
        tuple(sorted(alternatives, key=lambda a: natural_key(a.video))),
        tuple(sorted(unpaired, key=lambda s: natural_key(s.path))),
    )


def _scan_folder(
    video_paths: list[Path], subtitle_paths: list[Path], options: ScanOptions, shows: Callable[[Path], bool]
) -> tuple[list[MediaItem], list[Alternatives], list[SubtitleFile]]:
    # A VobSub pair is one subtitle: the `.idx` names it, and its `.sub` holds the pictures.
    index_files = {p.with_suffix("") for p in subtitle_paths if p.suffix.lower() == ".idx"}
    subtitle_paths = [p for p in subtitle_paths if p.suffix.lower() != ".sub" or p.with_suffix("") not in index_files]

    found = [read_subtitle(p, detect=options.detect_untagged_languages) for p in subtitle_paths]
    attached: list[list[SubtitleFile]] = [[] for _ in video_paths]
    alternatives: list[Alternatives] = []
    placed: set[int] = set()

    if video_paths and found:
        video_keys = name_keys([spaced(p.stem) for p in video_paths])
        # The words common to all subtitle names are found over the whole folder, whatever the language.
        subtitle_keys = name_keys([parse_subtitle_name(p.name).base for p in subtitle_paths])
        # Each language, forced and SDH variant is paired for itself: a video takes one file of each.
        variants: dict[tuple, list[int]] = {}
        for index, subtitle in enumerate(found):
            variants.setdefault((subtitle.language, subtitle.forced, subtitle.sdh), []).append(index)
        for indexes in variants.values():
            matches = pair(video_keys, [subtitle_keys[i] for i in indexes], [_size(subtitle_paths[i]) for i in indexes])
            for match in matches:
                attached[match.video].append(found[indexes[match.subtitle]])
                placed.add(indexes[match.subtitle])
                if match.alternatives:
                    others = tuple(found[indexes[a]] for a in match.alternatives)
                    placed.update(indexes[a] for a in match.alternatives)
                    alternatives.append(Alternatives(video_paths[match.video], others))

    items = [
        MediaItem(
            identify(path, alone=len(video_paths) == 1, shows=shows),
            MediaFile(path, path.suffix.lstrip(".").lower(), size=_size(path)),
            tuple(attached[index]),
        )
        for index, path in enumerate(video_paths)
    ]
    return items, alternatives, [s for i, s in enumerate(found) if i not in placed]
