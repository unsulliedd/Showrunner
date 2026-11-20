"""The window reads the files a job wrote again, so its views and plans show what is on disk and the read cache holds
it too: after Apply, after a queue item, after a job that stopped partway, and while it waits for the read. The first
two use real MKVToolNix files made in `tmp_path`; the others the stand-in remux stage of the Apply tests."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.jobs.store import JobStore
from showrunner.app.library.cache import load_cache, media_from_json
from showrunner.app.library.library import LibraryLoad
from showrunner.app.storage.paths import read_cache_path
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.tools.probe import Programs, probe
from showrunner.ui.quick.window import WindowController

from .test_apply import Setup, make_setup, real_statuses

COMMENTARY = "Commentary by Someone"
HEARING_IMPAIRED = "English (SDH)"


@pytest.fixture
def named_season(real_episode: Any, tmp_path: Path) -> list[Path]:
    """Two episodes whose tracks are named "Commentary by Someone" and "English (SDH)" without the flags those names
    imply; `real_episode` gives the program and a source file."""
    folder = tmp_path / "Show Name" / "Season 02"
    folder.mkdir(parents=True)
    videos = []
    for number in (1, 2):
        video = folder / f"Show Name - S02E0{number}.mkv"
        subprocess.run(
            [
                real_episode.mkvmerge, "-o", video,
                "--track-name", f"1:{HEARING_IMPAIRED}", "--track-name", f"2:{COMMENTARY}",
                real_episode.video,
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        videos.append(video)
    return videos


def flagged(file: MediaFile) -> tuple[list[str], list[str]]:
    """The names of the tracks holding the commentary flag and the hearing-impaired flag."""
    return (
        [t.name for t in file.tracks if t.flags.commentary],
        [t.name for t in file.tracks if t.flags.hearing_impaired],
    )


def open_season(qtbot: QtBot, real_episode: Any, videos: list[Path], tmp_path: Path) -> WindowController:
    """The season in the window with "Write flags the names imply" on, as the library read it before any write."""
    programs = Programs(mkvmerge=real_episode.mkvmerge)
    items = tuple(MediaItem(Episode("Show Name", 2, int(v.stem[-2:])), probe(v, programs)) for v in videos)
    controller = WindowController(statuses=real_statuses(real_episode.mkvmerge), jobs=JobStore(tmp_path / "j.db"))
    controller.model.add(LibraryLoad(items=items, roots=(videos[0].parent.parent,)))
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    controller.select(controller.tree.index_of(str(videos[0])).parent())
    controller.set_write_implied_flags(True)
    qtbot.waitUntil(lambda: not controller.planning and controller.can_apply)
    assert all(flagged(i.file) == ([], []) for i in items)
    return controller


def check_shows_what_was_written(
    qtbot: QtBot, controller: WindowController, real_episode: Any, videos: list[Path]
) -> None:
    """The library, the plan and the read cache all hold the flags the job wrote."""
    programs = Programs(mkvmerge=real_episode.mkvmerge)
    for video in videos:
        assert flagged(probe(video, programs)) == ([COMMENTARY], [HEARING_IMPAIRED])  # on disk
    qtbot.waitUntil(lambda: not controller.locked and not controller.planning and controller.change_count == 0)
    assert not controller.can_apply
    entries = load_cache(read_cache_path())
    for video in videos:
        item = controller.model.library.item(video)
        assert item is not None
        assert flagged(item.file) == ([COMMENTARY], [HEARING_IMPAIRED])
        assert flagged(media_from_json(video, entries[str(video.resolve())]["file"])) == (
            [COMMENTARY],
            [HEARING_IMPAIRED],
        )


def test_apply_shows_the_flags_it_wrote(
    qapp: QApplication, qtbot: QtBot, real_episode: Any, named_season: list[Path], tmp_path: Path
) -> None:
    controller = open_season(qtbot, real_episode, named_season, tmp_path)
    assert controller.change_count > 0
    with qtbot.waitSignal(controller.jobs.ended, timeout=60_000):
        controller.apply()
    check_shows_what_was_written(qtbot, controller, real_episode, named_season)
    controller.deleteLater()


def test_a_queue_item_shows_the_flags_it_wrote(
    qapp: QApplication, qtbot: QtBot, real_episode: Any, named_season: list[Path], tmp_path: Path
) -> None:
    controller = open_season(qtbot, real_episode, named_season, tmp_path)
    with qtbot.waitSignal(controller.queue.noted, timeout=10_000):
        controller.place_action("queue")
    controller.queue.start()
    qtbot.waitUntil(lambda: not controller.jobs.running and not controller.queue.going, timeout=60_000)
    assert [row["state"] for row in controller.queue.rows] == ["done"]
    check_shows_what_was_written(qtbot, controller, real_episode, named_season)
    controller.stop_jobs()
    controller.deleteLater()


@pytest.fixture
def setup(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> Iterator[Setup]:
    made = make_setup(qtbot, tmp_path)
    yield made
    made.hold.set()
    made.controller.stop_jobs()
    made.controller.deleteLater()


def title(setup: Setup, path: Path) -> str:
    item = setup.controller.model.library.item(path)
    assert item is not None
    return item.file.title


def test_a_job_cancelled_partway_reads_again_the_file_it_was_writing_and_no_other(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    setup.hold.clear()
    controller.apply()
    # Only once the first step holds half written: right after the start the cancel can still come before the step.
    qtbot.waitUntil(lambda: controller.jobs.running and controller.jobs.view["rows"][0]["phases"][0]["percent"] == 50)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.jobs.cancel()
    qtbot.waitUntil(lambda: title(setup, setup.season[0]) == "Read again")
    assert {title(setup, p) for p in setup.season[1:]} == {""}  # the steps that never started were not touched


def test_a_failed_step_reads_its_file_again_with_the_ones_that_were_written(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    made = make_setup(qtbot, tmp_path, fail="S01E03")
    with qtbot.waitSignal(made.controller.jobs.ended, timeout=10_000):
        made.controller.apply()
    qtbot.waitUntil(lambda: title(made, made.season[2]) == "Read again")
    assert {title(made, p) for p in made.season} == {"Read again"}
    made.controller.deleteLater()


def test_the_place_stays_locked_until_the_files_are_read_again(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    reading, release = threading.Event(), threading.Event()
    stand_in = controller._read_file
    assert stand_in is not None

    def slow(path: Path) -> MediaFile:
        reading.set()
        release.wait(10)
        return replace(stand_in(path), title="Slowly read")

    controller._read_file = slow
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    qtbot.waitUntil(reading.is_set)
    # The job has ended, and the plan on screen still comes from the files as they were before it.
    assert not controller.jobs.running
    assert controller.locked
    assert not controller.can_apply
    assert not controller.can_change_library  # Close all folders waits too
    with qtbot.waitSignal(controller.loading_changed):
        release.set()
    qtbot.waitUntil(lambda: not controller.locked)
    assert controller.can_change_library
    assert title(setup, setup.season[0]) == "Slowly read"
