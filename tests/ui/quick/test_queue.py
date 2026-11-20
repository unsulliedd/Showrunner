"""The queue through the window controller: Add to queue from the library's menu with the settings of that moment,
Start and Pause, Cancel, Retry and Remove, a file changed on disk after it was queued, a place queued twice, and the
queue after a restart. The season and the stand-in mux stage are those of the Apply tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.jobs.run import StalePreviewError
from showrunner.app.jobs.stages import TracksStage
from showrunner.core.media import MediaFile
from showrunner.tools.probe import Programs
from showrunner.ui.quick import window
from showrunner.ui.quick.window import WindowController

from .conftest import program_statuses
from .test_apply import COMMENTARY, Setup, StandInMux, make_setup


@pytest.fixture
def setup(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> Iterator[Setup]:
    made = make_setup(qtbot, tmp_path)
    yield made
    made.hold.set()
    made.controller.stop_jobs()
    made.controller.deleteLater()


def add(controller: WindowController, qtbot: QtBot) -> None:
    """Add the selected place from the library's menu and wait until the queue says what it did."""
    (action,) = [a for a in controller.place_actions if a["key"] == "queue"]
    assert action["enabled"]
    with qtbot.waitSignal(controller.queue.noted, timeout=10_000):
        controller.place_action("queue")


def states(controller: WindowController) -> list[str]:
    return [row["state"] for row in controller.queue.rows]


def wait_idle(controller: WindowController, qtbot: QtBot) -> None:
    qtbot.waitUntil(lambda: not controller.jobs.running and not controller.queue.going, timeout=10_000)


def test_a_queued_place_keeps_the_settings_it_had_when_added(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    add(controller, qtbot)
    assert controller.queue.note == "Show Name (2020), Season 1 was added to the queue: 10 files."
    (row,) = controller.queue.rows
    assert (row["state"], row["files"]) == ("waiting", "10 files")
    assert setup.store.unfinished()  # a stored job, which the next start does not offer: the queue lists it
    controller.jobs.check_unfinished()
    assert controller.jobs.offer == {}
    # Keeping the commentary afterwards leaves nothing to write in the workspace; the queued item still drops it.
    controller.toggle_keep(COMMENTARY)
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.change_count == 0
    controller.queue.start()
    wait_idle(controller, qtbot)
    assert states(controller) == ["done"]
    assert sorted(p.name for p in setup.bin.iterdir()) == sorted(p.name for p in setup.season)


def test_excluded_and_left_out_files_are_not_queued(setup: Setup, qtbot: QtBot) -> None:
    controller, eighth, ninth = setup.controller, setup.season[7], setup.season[8]
    controller.exclude_file(str(ninth), True)
    controller.set_file_in_run(str(eighth), False)
    add(controller, qtbot)
    assert controller.queue.rows[0]["files"] == "8 files"
    controller.queue.start()
    wait_idle(controller, qtbot)
    assert eighth.read_bytes() == ninth.read_bytes() == b"original"
    assert len(list(setup.bin.iterdir())) == 8


def test_items_run_one_after_another(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    for episode in setup.season[:2]:
        controller.select(controller.tree.index_of(str(episode)))
        add(controller, qtbot)
    assert [r["name"] for r in controller.queue.rows] == [
        "Show Name (2020) · Season 1, Episode One",
        "Show Name (2020) · Season 1, Episode Two",
    ]
    assert controller.queue.status == "2 items to run"
    controller.queue.start()
    wait_idle(controller, qtbot)
    assert states(controller) == ["done", "done"]
    assert sorted(p.name for p in setup.bin.iterdir()) == sorted(p.name for p in setup.season[:2])


def test_pause_lets_the_running_step_end_and_start_goes_on(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    add(controller, qtbot)
    setup.hold.clear()
    controller.queue.start()
    qtbot.waitUntil(lambda: controller.jobs.view.get("rows", [{}])[0].get("phases", [{}])[0].get("percent") == 50)
    assert states(controller) == ["running"]
    assert controller.queue.rows[0]["can_cancel"]
    assert not controller.queue.rows[0]["can_remove"]
    controller.queue.pause()
    assert controller.queue.status.startswith("Pausing once the running step ends")
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        setup.hold.set()
    assert states(controller) == ["interrupted"]
    assert controller.queue.rows[0]["detail"].startswith("Stopped after 1 of 10 steps.")
    assert len(list(setup.bin.iterdir())) == 1  # the step that was running ended; no other started
    assert controller.jobs.view["summary"].startswith("Paused.")
    controller.queue.start()
    wait_idle(controller, qtbot)
    assert states(controller) == ["done"]
    assert len(list(setup.bin.iterdir())) == 10


def test_cancel_stops_the_running_item_and_retry_goes_on_with_it(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    add(controller, qtbot)
    setup.hold.clear()
    controller.queue.start()
    qtbot.waitUntil(lambda: controller.jobs.view.get("rows", [{}])[0].get("phases", [{}])[0].get("percent") == 50)
    job_id = controller.queue.rows[0]["id"]
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.queue.cancel(job_id)
    wait_idle(controller, qtbot)
    (row,) = controller.queue.rows
    assert (row["state"], row["can_retry"], row["can_remove"]) == ("cancelled", True, True)
    assert all(p.read_bytes() == b"original" for p in setup.season)
    setup.hold.set()
    controller.queue.start()  # a cancelled item does not run again until Retry
    assert states(controller) == ["cancelled"]
    controller.queue.retry(job_id)
    wait_idle(controller, qtbot)
    assert states(controller) == ["done"]
    assert len(list(setup.bin.iterdir())) == 10


def test_cancel_on_the_jobs_tab_cancels_the_item_and_the_queue_does_not_start_it_again(
    setup: Setup, qtbot: QtBot
) -> None:
    controller = setup.controller
    add(controller, qtbot)
    setup.hold.clear()
    controller.queue.start()
    qtbot.waitUntil(lambda: controller.jobs.view.get("rows", [{}])[0].get("phases", [{}])[0].get("percent") == 50)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.jobs.cancel()  # the Jobs tab's and the top bar's Cancel
    wait_idle(controller, qtbot)
    assert states(controller) == ["cancelled"]
    assert controller.jobs.view["summary"].endswith("Retry in the queue goes on with the rest.")


def test_a_failed_item_says_why_and_retry_runs_only_its_failed_steps(
    qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    made = make_setup(qtbot, tmp_path, fail="S01E03")
    controller = made.controller
    add(controller, qtbot)
    controller.queue.start()
    wait_idle(controller, qtbot)
    (row,) = controller.queue.rows
    assert row["state"] == "failed"
    assert row["detail"].startswith("The new file did not pass its check, so it was removed.")
    assert row["can_retry"]
    controller.queue.retry(row["id"])
    wait_idle(controller, qtbot)
    assert states(controller) == ["failed"]
    assert len(list(made.bin.iterdir())) == 9  # the files done before were not written again
    assert made.season[2].read_bytes() == b"original"
    controller.queue.remove(row["id"])
    assert controller.queue.rows == []
    made.controller.stop_jobs()
    made.controller.deleteLater()


def test_a_file_changed_on_disk_after_it_was_queued_is_not_written(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    add(controller, qtbot)
    setup.season[4].write_bytes(b"changed by another program")
    controller.queue.start()
    wait_idle(controller, qtbot)
    (row,) = controller.queue.rows
    assert row["state"] == "changed"
    # The other nine files were written, and the row says so beside the one that changed.
    assert row["detail"].startswith("9 of 10 steps written. 1 not written: a file changed on disk after it was queued.")
    assert not row["can_retry"]
    assert setup.season[4].read_bytes() == b"changed by another program"
    assert len(list(setup.bin.iterdir())) == 9


def test_a_place_queued_again_replaces_its_waiting_item_and_an_episode_inside_it_is_refused(
    setup: Setup, qtbot: QtBot
) -> None:
    controller = setup.controller
    add(controller, qtbot)
    first = controller.queue.rows[0]["id"]
    add(controller, qtbot)
    (row,) = controller.queue.rows
    assert row["id"] != first
    assert controller.queue.note.startswith("Show Name (2020), Season 1 was added to the queue again")
    controller.select(controller.tree.index_of(str(setup.season[2])))
    qtbot.waitUntil(lambda: not controller.planning)
    add(controller, qtbot)
    assert [r["id"] for r in controller.queue.rows] == [row["id"]]
    assert controller.queue.note.startswith("Show Name (2020) · Season 1, Episode Three was not queued: a file of it")


def test_the_queue_comes_back_after_a_restart_paused_and_goes_on(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    add(controller, qtbot)
    setup.hold.clear()
    controller.queue.start()
    qtbot.waitUntil(lambda: controller.jobs.view.get("rows", [{}])[0].get("phases", [{}])[0].get("percent") == 50)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.stop_jobs()  # the window closes mid-step
    setup.hold.set()
    after = WindowController(
        statuses=program_statuses,
        jobs=setup.store,
        make_pipeline=lambda _s: (
            TracksStage(),
            StandInMux(Path("mkvmerge"), Programs(mkvmerge=Path("mkvmerge")), bin=setup.bin),
        ),
        read=lambda p: MediaFile(p, ""),
    )
    after.start()
    qtbot.waitUntil(lambda: after.programs[0]["state"] != "checking")
    assert states(after) == ["interrupted"]  # not cancelled: closing the window is no Cancel
    assert not after.queue.going
    assert not after.jobs.running
    assert after.jobs.offer == {}  # the queue lists it; it is not offered as an earlier Apply
    after.queue.start()
    wait_idle(after, qtbot)
    assert states(after) == ["done"]
    assert len(list(setup.bin.iterdir())) == 10
    after.stop_jobs()
    after.deleteLater()


@pytest.mark.parametrize(
    ("error", "note"),
    [
        (StalePreviewError(), "The plan changed while the place was being queued"),
        (sqlite3.OperationalError("disk I/O error"), "The place could not be queued: disk I/O error"),
    ],
)
def test_a_job_that_cannot_be_stored_is_not_queued_and_leaves_nothing_locked(
    setup: Setup, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, error: Exception, note: str
) -> None:
    controller = setup.controller

    def refuse(*_args: object, **_kwargs: object) -> int:
        raise error

    monkeypatch.setattr(window, "create_job", refuse)
    add(controller, qtbot)
    assert controller.queue.note.startswith(note)
    assert controller.queue.rows == []
    assert not controller.locked
    assert controller.can_queue


def test_an_apply_whose_job_cannot_be_stored_says_why_and_leaves_nothing_locked(
    setup: Setup, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = setup.controller

    def refuse(*_args: object, **_kwargs: object) -> int:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(window, "create_job", refuse)
    controller.apply()
    qtbot.waitUntil(lambda: not controller.applying)
    assert controller.apply_message == "Apply could not get ready: disk I/O error"
    assert not controller.locked
    assert controller.can_apply
