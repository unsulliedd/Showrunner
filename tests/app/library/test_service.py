from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from showrunner.app.library import service
from showrunner.app.library.service import load_library
from showrunner.core.media import MediaFile
from showrunner.tools.probe import ProbeError, Programs

PROGRAMS = Programs(Path("mkvmerge"), Path("mkvextract"), Path("ffprobe"))


def fake_read(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
    return MediaFile(path, "matroska", duration=60.0)


def test_every_video_is_scanned_then_probed(make: Callable[..., Path], tmp_path: Path) -> None:
    make("Show/S01/Show S01E01.mkv")
    make("Show/S01/Show S01E02.mkv")
    make("Show/S01/Show S01E01.tr.srt")
    calls: list[tuple[int, int]] = []
    load = load_library(
        [tmp_path / "Show"],
        programs=PROGRAMS,
        read=fake_read,
        progress=lambda done, total, _path: calls.append((done, total)),
    )
    assert [i.file.duration for i in load.items] == [60.0, 60.0]
    assert [i.identity.episode for i in load.items] == [1, 2]
    assert len(load.items[0].subtitles) == 1
    assert calls == [(1, 2), (2, 2)]
    assert load.roots == (tmp_path / "Show",)
    assert not load.cancelled


def test_the_scan_names_the_videos_about_to_be_read_and_leaves_out_known_ones(
    make: Callable[..., Path], tmp_path: Path
) -> None:
    known = make("Show/Show S01E01.mkv")
    make("Show/Show S01E02.mkv")
    told: list[tuple[str, ...]] = []
    load_library(
        [tmp_path / "Show"],
        known=[known],
        programs=PROGRAMS,
        read=fake_read,
        scanned=lambda items: told.append(tuple(i.file.path.name for i in items)),
    )
    assert told == [("Show S01E02.mkv",)]


def test_a_file_that_cannot_be_read_is_reported_and_the_rest_go_on(make: Callable[..., Path], tmp_path: Path) -> None:
    make("Show/Show S01E01.mkv")
    make("Show/Show S01E02.mkv")

    def read(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        if "E01" in path.name:
            raise ProbeError("broken header")
        return fake_read(path, programs, cancel=cancel)

    load = load_library([tmp_path / "Show"], programs=PROGRAMS, read=read)
    assert [(f.path.name, f.reason) for f in load.failures] == [("Show S01E01.mkv", "broken header")]
    assert load.items[1].file.duration == 60.0


def test_cancelling_keeps_what_was_scanned(make: Callable[..., Path], tmp_path: Path) -> None:
    for number in range(1, 4):
        make(f"Show/Show S01E0{number}.mkv")
    cancel = threading.Event()

    def progress(done: int, total: int, path: Path) -> None:
        cancel.set()

    load = load_library([tmp_path / "Show"], programs=PROGRAMS, read=fake_read, progress=progress, cancel=cancel)
    assert load.cancelled
    assert [i.file.duration for i in load.items] == [60.0, None, None]


def test_cancelling_before_the_probe_skips_it(make: Callable[..., Path], tmp_path: Path) -> None:
    make("Show/Show S01E01.mkv")
    cancel = threading.Event()
    cancel.set()
    load = load_library([tmp_path / "Show"], programs=PROGRAMS, read=fake_read, cancel=cancel)
    assert load.cancelled
    assert len(load.items) == 1
    assert load.items[0].file.duration is None


def test_known_videos_are_not_probed_again(make: Callable[..., Path], tmp_path: Path) -> None:
    known = make("Show/Show S01E01.mkv")
    make("Show/Show S01E02.mkv")
    seen: list[Path] = []

    def read(path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        seen.append(path)
        return fake_read(path, programs, cancel=cancel)

    load = load_library([tmp_path / "Show"], known=[known], programs=PROGRAMS, read=read)
    assert [p.name for p in seen] == ["Show S01E02.mkv"]
    assert len(load.items) == 1


def test_without_a_program_the_videos_come_back_as_scanned(make: Callable[..., Path], tmp_path: Path) -> None:
    make("Show/Show S01E01.mkv")

    def read(*_args: object, **_kwargs: object) -> MediaFile:
        raise AssertionError("nothing should be probed")

    load = load_library([tmp_path / "Show"], programs=Programs(), read=read)
    assert len(load.items) == 1
    assert load.failures == ()


def test_a_cancel_while_the_programs_are_checked_ends_the_load_as_cancelled(
    make: Callable[..., Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make("Show/Show S01E01.mkv")
    cancel = threading.Event()

    def checked(given: threading.Event | None) -> Programs:
        cancel.set()  # pressed while a program answered; the check then counts the program as broken
        return Programs()

    monkeypatch.setattr(service, "media_programs", checked)
    load = load_library([tmp_path / "Show"], read=fake_read, cancel=cancel)
    assert load.cancelled
    assert len(load.items) == 1
