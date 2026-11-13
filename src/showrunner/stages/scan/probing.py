"""Reading the tracks, chapters and attachments of scanned videos, as a separate step from the scan."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from showrunner.core.media import MediaFile, MediaItem
from showrunner.tools.probe import ProbeError, Programs, probe
from showrunner.tools.process import ProcessCancelledError, ProcessError

# Called after each file: files done, files in all, the file just handled.
type Progress = Callable[[int, int, Path], None]


class Reader(Protocol):
    def __call__(self, path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile: ...


@dataclass(frozen=True, slots=True)
class ProbeFailure:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class ProbeBatch:
    """Every item given, in order; an item that failed or was never reached keeps its scanned file."""

    items: tuple[MediaItem, ...]
    failures: tuple[ProbeFailure, ...]
    cancelled: bool


def probe_items(
    items: Iterable[MediaItem],
    *,
    programs: Programs,
    read: Reader = probe,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> ProbeBatch:
    """Probe the file of each item with `programs`, which the caller detects once for the whole batch."""
    items = tuple(items)
    probed = list(items)
    failures: list[ProbeFailure] = []
    cancelled = False
    for index, item in enumerate(items):
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        path = item.file.path
        try:
            probed[index] = replace(item, file=read(path, programs, cancel=cancel))
        except ProcessCancelledError:
            cancelled = True
            break
        except (ProbeError, ProcessError, OSError) as error:
            failures.append(ProbeFailure(path, str(error)))
        if progress is not None:
            progress(index + 1, len(items), path)
    return ProbeBatch(tuple(probed), tuple(failures), cancelled)
