"""Loading a library: scan the dropped paths, then read the tracks of every video found."""

from __future__ import annotations

import threading
from collections.abc import Collection, Iterable
from pathlib import Path

from showrunner.app.dependencies.service import check, media_programs
from showrunner.app.library.cache import CachedReader, load_cache, save_cache
from showrunner.app.library.library import LibraryLoad
from showrunner.stages.scan import ScanOptions, probe_items, scan
from showrunner.stages.scan.probing import Progress, Reader
from showrunner.tools.dependencies.detect import DependencyStatus
from showrunner.tools.dependencies.specs import SPEC_BY_ID
from showrunner.tools.probe import Programs, probe


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
) -> LibraryLoad:
    """Scan `paths` and probe each video that is not in `known`.

    The programs are detected once, here, unless the caller passes them. Without any program to read
    tracks the videos are returned as scanned and nothing is reported as failed. With a `cache` file a video
    unchanged since it was last read is served from it; what was read is saved there, also when cancelled.
    """
    paths = tuple(paths)
    roots = tuple(p for p in paths if p.is_dir())
    result = scan(paths, options)
    skipped = set(known)
    items = tuple(i for i in result.items if i.file.path not in skipped)
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


def reading_statuses(cancel: threading.Event | None = None) -> dict[str, DependencyStatus]:
    """The state of the programs that read tracks, by program ID."""
    return {spec_id: check(SPEC_BY_ID[spec_id], cancel) for spec_id in ("mkvtoolnix", "ffmpeg")}
