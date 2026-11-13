from __future__ import annotations

import threading
from pathlib import Path

from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.stages.scan import probe_items
from showrunner.tools.probe import ProbeError, Programs
from showrunner.tools.process import ProcessCancelledError

PROGRAMS = Programs(Path("mkvmerge.exe"), Path("mkvextract.exe"), Path("ffprobe.exe"))


def items(count: int) -> list[MediaItem]:
    return [MediaItem(Movie(f"m{n}"), MediaFile(Path(f"m{n}.mkv"), "mkv")) for n in range(count)]


def fake_read(path: Path, programs: Programs, cancel: threading.Event | None) -> MediaFile:
    return MediaFile(path, "matroska", duration=60.0)


def test_every_file_is_probed_with_the_programs_given_once() -> None:
    seen: list[Programs] = []

    def read(path: Path, programs: Programs, cancel: threading.Event | None) -> MediaFile:
        seen.append(programs)
        return fake_read(path, programs, cancel)

    batch = probe_items(items(3), programs=PROGRAMS, read=read)
    assert [i.file.duration for i in batch.items] == [60.0] * 3
    assert seen == [PROGRAMS] * 3
    assert batch.failures == ()
    assert not batch.cancelled


def test_progress_is_reported_after_each_file() -> None:
    calls: list[tuple[int, int, Path]] = []
    probe_items(items(2), programs=PROGRAMS, read=fake_read, progress=lambda *args: calls.append(args))
    assert calls == [(1, 2, Path("m0.mkv")), (2, 2, Path("m1.mkv"))]


def test_a_file_that_fails_is_reported_and_the_batch_goes_on() -> None:
    def read(path: Path, programs: Programs, cancel: threading.Event | None) -> MediaFile:
        if path.name == "m1.mkv":
            raise ProbeError("broken header")
        return fake_read(path, programs, cancel)

    calls: list[int] = []
    batch = probe_items(items(3), programs=PROGRAMS, read=read, progress=lambda done, *_: calls.append(done))
    assert [(f.path.name, f.reason) for f in batch.failures] == [("m1.mkv", "broken header")]
    assert [i.file.duration for i in batch.items] == [60.0, None, 60.0]  # the failed one keeps its scanned file
    assert calls == [1, 2, 3]


def test_cancelling_stops_before_the_next_file_and_keeps_the_rest_as_scanned() -> None:
    cancel = threading.Event()

    def progress(done: int, total: int, path: Path) -> None:
        if done == 2:
            cancel.set()

    batch = probe_items(items(4), programs=PROGRAMS, read=fake_read, progress=progress, cancel=cancel)
    assert batch.cancelled
    assert [i.file.duration for i in batch.items] == [60.0, 60.0, None, None]


def test_a_probe_stopped_by_the_cancellation_ends_the_batch() -> None:
    def read(path: Path, programs: Programs, cancel: threading.Event | None) -> MediaFile:
        raise ProcessCancelledError("cancelled", ["ffprobe"])

    batch = probe_items(items(2), programs=PROGRAMS, read=read)
    assert batch.cancelled
    assert batch.failures == ()
