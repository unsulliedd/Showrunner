"""Loading a library: scan the dropped paths, then read the tracks of every video found."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Collection, Iterable, Mapping
from pathlib import Path

from showrunner.app.dependencies.service import media_programs
from showrunner.app.library.cache import CachedReader, load_cache, save_cache
from showrunner.app.library.library import LibraryLoad
from showrunner.core.media import MediaFile, MediaItem
from showrunner.stages.scan import ScanOptions, probe_items, scan
from showrunner.stages.scan.probing import Progress, Reader
from showrunner.tools.probe import Programs, probe

_log = logging.getLogger(__name__)


def load_library(
    paths: Iterable[Path],
    *,
    options: ScanOptions | None = None,
    known: Collection[Path] = (),
    programs: Programs | None = None,
    read: Reader = probe,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
    cache: Path | None = None,
    scanned: Callable[[tuple[MediaItem, ...]], None] | None = None,
) -> LibraryLoad:
    """Scan `paths` and probe each video that is not in `known`.

    The programs are detected once, here, unless the caller passes them. Without any program to read
    tracks the videos are returned as scanned and nothing is reported as failed. With a `cache` file a video
    unchanged since it was last read is served from it; what was read is saved there, also when cancelled.
    `scanned` is told which videos are about to be read, once the scan has found them.
    """
    paths = tuple(paths)
    roots = tuple(p for p in paths if p.is_dir())
    result = scan(paths, options)
    skipped = set(known)
    items = tuple(i for i in result.items if i.file.path not in skipped)
    if scanned is not None:
        scanned(items)
    fresh = {i.file.path for i in items}
    alternatives = tuple(a for a in result.alternatives if a.video in fresh)
    unpaired = result.unpaired
    programs = programs if programs is not None else media_programs(cancel)
    # After the programs: a cancel during their check counts them as broken, which must not read as "none found".
    if cancel is not None and cancel.is_set():
        return LibraryLoad(items, alternatives, unpaired, (), cancelled=True, roots=roots)
    if programs.mkvmerge is None and programs.ffprobe is None:
        return LibraryLoad(items, alternatives, unpaired, roots=roots)
    if cache is None:
        batch = probe_items(items, programs=programs, read=read, progress=progress, cancel=cancel)
        return LibraryLoad(batch.items, alternatives, unpaired, batch.failures, batch.cancelled, roots)
    cached = CachedReader(read, load_cache(cache))
    cached.drop_gone(roots, result.items)
    try:
        batch = probe_items(items, programs=programs, read=cached, progress=progress, cancel=cancel)
    finally:
        if cached.changed:
            save_cache(cache, cached.entries)
    return LibraryLoad(batch.items, alternatives, unpaired, batch.failures, batch.cancelled, roots)


def read_again(
    paths: Mapping[Path, Path],
    programs: Programs,
    *,
    read: Reader = probe,
    cache: Path | None = None,
) -> dict[Path, MediaFile]:
    """Read the files a job wrote again. `paths` maps the path the library knows a file by to where the file is now,
    which differs after a remux to a new name; the result is keyed by the first. A file that cannot be read is left
    out, so the library keeps what it read before.

    With a `cache` file the entries of what was read are renewed, and the entry of a path a file left is dropped, so
    the next start does not serve the file as it was before the write."""
    cached = CachedReader(read, load_cache(cache) if cache is not None else {})
    files: dict[Path, MediaFile] = {}
    for old, new in paths.items():
        try:
            files[old] = cached(new, programs, cancel=None)
        except Exception:  # one unreadable file does not keep the others from the window
            _log.exception("Could not read %s again", new)
            continue
        if new != old:
            cached.forget(old)
    if cache is not None and cached.changed:
        save_cache(cache, cached.entries)
    return files
