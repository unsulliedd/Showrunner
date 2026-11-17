"""Review and Apply through the window controller: leave out, a stamped preview at Apply, the job on a pool thread,
the lock, Cancel, the unfinished-job offer and the files read again. The season lives in `tmp_path` as small
placeholder files; a stand-in mux stage writes and checks nothing real. A last test remuxes a real file."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.jobs.stages import MuxStage, StagePlan, StepResult, TracksStage
from showrunner.app.jobs.store import JobStore
from showrunner.app.library.library import Library
from showrunner.core.media import MediaFile
from showrunner.stages.mux import Failure, MuxPlan, MuxResult, VerifyProblem
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.probe import Programs
from showrunner.tools.process import ProcessCancelledError
from showrunner.ui.quick.library import LEFT_OUT
from showrunner.ui.quick.window import WindowController

from .conftest import neutral_library, program_statuses

COMMENTARY = 2


@dataclass(frozen=True)
class StandInMux(MuxStage):
    """Plans like the mux stage; applying moves the original to `bin` and writes a new file in its place. A file
    whose name holds `fail` fails its check; with `hold` set, a step waits for it (or for Cancel) half written."""

    fail: str = ""
    hold: threading.Event | None = field(default=None, repr=False, compare=False)
    bin: Path = Path("bin")

    id: ClassVar[str] = "mux"

    def apply(self, plan: StagePlan, cancel: threading.Event | None, progress: Any = None) -> StepResult:
        mux = plan.plan
        assert isinstance(mux, MuxPlan)
        if progress is not None:
            progress(0.5)
        while self.hold is not None and not self.hold.is_set():
            if cancel is not None and cancel.wait(0.01):
                raise ProcessCancelledError("cancelled", ())
        if self.fail and self.fail in mux.source.name:
            problem = VerifyProblem("language", 1, "tur", "eng")
            return StepResult(False, "verify", MuxResult(failure=Failure.VERIFY, problems=(problem,)))
        if progress is not None:
            progress(1.0)
        self.bin.mkdir(exist_ok=True)
        mux.source.rename(self.bin / mux.source.name)
        mux.output.write_bytes(b"new file")
        return StepResult(True, "", MuxResult(mux.output, recycled=(mux.source,)))


@dataclass
class Setup:
    controller: WindowController
    library: Library
    season: list[Path]
    bin: Path
    store: JobStore
    hold: threading.Event


def rooted_library(root: Path) -> Library:
    """The neutral library with the first season's files written under `root`, their sizes and modification times
    as the library read them."""
    library = neutral_library()
    items = []
    for item in library.items:
        path = root / item.file.path
        if item.file.path.parent.name == "Season 1" and item.file.path.parent.parent.name == "Show Name (2020)":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original")
        size, modified = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else (0, 0)
        items.append(replace(item, file=replace(item.file, path=path, size=size, modified_ns=modified)))
    return replace(library, items=tuple(items), alternatives=())


def make_setup(qtbot: QtBot, tmp_path: Path, **stand_in: Any) -> Setup:
    hold = threading.Event()
    hold.set()
    bin = tmp_path / "bin"
    stage = StandInMux(Path("mkvmerge"), Programs(mkvmerge=Path("mkvmerge")), hold=hold, bin=bin, **stand_in)
    store = JobStore(tmp_path / "jobs.sqlite3")

    def read(path: Path) -> MediaFile:
        return replace(next(i.file for i in library.items if i.file.path == path), title="Read again")

    controller = WindowController(
        statuses=program_statuses,
        get_program=lambda _id: None,
        jobs=store,
        make_pipeline=lambda _statuses: (TracksStage(), stage),
        read=read,
    )
    library = rooted_library(tmp_path / "media")
    controller.model.set_library(library)
    controller.start()
    season = [i.file.path for i in library.items if i.file.path.exists()]
    controller.select(controller.tree.index_of(str(season[0])).parent())
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    qtbot.waitUntil(lambda: not controller.planning)
    if controller.matrix["headers"][COMMENTARY]["state"] == "kept":  # a working copy saved by an earlier window
        controller.toggle_keep(COMMENTARY)
    qtbot.waitUntil(lambda: not controller.planning and controller.change_count > 0)
    return Setup(controller, library, season, bin, store, hold)


@pytest.fixture
def setup(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> Iterator[Setup]:
    made = make_setup(qtbot, tmp_path)
    yield made
    made.hold.set()
    made.controller.stop_jobs()
    made.controller.deleteLater()


def test_apply_writes_the_run_and_leaves_out_a_file(setup: Setup, qtbot: QtBot) -> None:
    controller, ninth = setup.controller, setup.season[8]
    every = controller.change_count
    controller.leave_out_file(str(ninth), True)
    assert controller.tree.index_of(str(ninth)).data(LEFT_OUT) is True
    assert controller.change_count == every - controller.review["rows"][0]["count"]
    assert controller.can_apply
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.apply()
    rows = controller.jobs.view["rows"]
    assert [r["state"] for r in rows] == ["done"] * 9
    assert [p["state"] for p in rows[0]["phases"]] == ["done"] * 4
    assert rows[0]["result"] == [
        "Checked: 6 tracks, the title and the length are as planned.",
        "The original went to the Recycle Bin.",
    ]
    assert sorted(p.name for p in setup.bin.iterdir()) == sorted(p.name for p in setup.season if p != ninth)
    assert ninth.read_bytes() == b"original"
    # The written files are read again and the batch opened again with them.
    qtbot.waitUntil(lambda: controller.model.library.item(setup.season[0]).file.title == "Read again")
    assert controller.model.library.item(ninth).file.title == ""
    assert setup.store.unfinished() == []


def test_a_left_out_group_is_not_written_and_its_options_stay(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    before = controller.change_count
    controller.set_in_run("tracks", False)
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.change_count < before
    assert controller.review["groups"][0]["in_run"] is False
    assert controller.rules  # the choices stay in the working copy
    assert not controller.can_apply  # nothing else is planned: Names has no template here


def test_a_failed_check_leaves_the_original_and_is_worded(qapp: QApplication, qtbot: QtBot, tmp_path: Path) -> None:
    made = make_setup(qtbot, tmp_path, fail="S01E03")
    with qtbot.waitSignal(made.controller.jobs.ended, timeout=10_000):
        made.controller.apply()
    third = made.controller.jobs.view["rows"][2]
    assert third["state"] == "failed"
    assert [p["state"] for p in third["phases"]] == ["done", "failed", "waiting", "waiting"]
    assert third["result"] == [
        "The new file did not pass its check, so it was removed. The original was not touched.",
        "Track 2: the language is eng; tur was planned.",
    ]
    assert made.season[2].read_bytes() == b"original"
    assert "1 failed" in made.controller.jobs.view["summary"]
    made.controller.deleteLater()


def test_a_file_changed_on_disk_refuses_to_start(setup: Setup, qtbot: QtBot) -> None:
    setup.season[4].write_bytes(b"changed by another program")
    setup.controller.apply()
    qtbot.waitUntil(lambda: not setup.controller.applying)
    assert setup.controller.apply_message.startswith("1 file changed on disk since it was read")
    assert not setup.bin.exists()
    assert setup.store.unfinished() == []
    assert not setup.controller.jobs.running


def test_a_file_written_with_the_same_size_refuses_to_start(setup: Setup, qtbot: QtBot) -> None:
    # A header edit by another program can keep the size; the later modification time gives it away.
    path = setup.season[4]
    read_at = path.stat().st_mtime_ns
    path.write_bytes(b"ORIGINAL")
    os.utime(path, ns=(read_at + 1_000_000_000, read_at + 1_000_000_000))
    setup.controller.apply()
    qtbot.waitUntil(lambda: not setup.controller.applying)
    assert setup.controller.apply_message.startswith("1 file changed on disk since it was read")
    assert setup.store.unfinished() == []


def test_the_batch_is_locked_while_its_job_runs_and_others_stay_open(setup: Setup, qtbot: QtBot) -> None:
    controller = setup.controller
    setup.hold.clear()
    controller.apply()
    qtbot.waitUntil(lambda: controller.jobs.running)
    assert controller.locked
    assert not controller.can_apply
    rules = controller.rules
    controller.toggle_keep(COMMENTARY)
    controller.leave_out_file(str(setup.season[0]), True)
    controller.set_in_run("names", False)
    assert controller.rules == rules
    assert not controller.left_out.files
    assert not controller.left_out.groups
    qtbot.waitUntil(lambda: controller.jobs.view["rows"][0]["phases"][0]["percent"] == 50)
    assert controller.jobs.status == "Applying Show Name (2020), Season 1 · 0 of 10"
    movie = next(i for i in setup.library.items if "Movie.Title" in i.file.path.name)
    controller.select(controller.tree.index_of(str(movie.file.path)))
    assert not controller.locked
    setup.hold.set()
    qtbot.waitUntil(lambda: not controller.jobs.running, timeout=10_000)


def test_cancel_stops_mid_step_and_the_job_is_offered_at_the_next_start(
    setup: Setup, qapp: QApplication, qtbot: QtBot, tmp_path: Path
) -> None:
    controller = setup.controller
    setup.hold.clear()
    controller.apply()
    # Cancel only once the first step holds half written: right after the start the cancel can still come before
    # the step, which then never runs.
    qtbot.waitUntil(lambda: controller.jobs.running and controller.jobs.view["rows"][0]["phases"][0]["percent"] == 50)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.jobs.cancel()
    view = controller.jobs.view
    assert view["rows"][0]["state"] == "stopped"
    assert view["summary"].startswith("Cancelled.")
    assert all(p.read_bytes() == b"original" for p in setup.season)
    (job,) = setup.store.unfinished()
    # The next start offers it; nothing resumes until Resume.
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
    qtbot.waitUntil(lambda: after.jobs.offer.get("id") == job.id)
    assert after.jobs.offer["resumable"] is True
    assert not after.jobs.running
    with qtbot.waitSignal(after.jobs.ended, timeout=10_000):
        after.jobs.resume_offer()
    assert after.jobs.offer == {}
    assert len(list(setup.bin.iterdir())) == 10
    assert setup.store.unfinished() == []
    after.deleteLater()


def test_a_job_from_another_version_can_only_be_discarded(
    setup: Setup, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = setup.controller
    setup.hold.clear()
    controller.apply()
    qtbot.waitUntil(lambda: controller.jobs.running)
    with qtbot.waitSignal(controller.jobs.ended, timeout=10_000):
        controller.jobs.cancel()
    monkeypatch.setattr("showrunner.app.jobs.store.__version__", "0.0.0")
    controller.jobs.check_unfinished()
    offer = controller.jobs.offer
    assert offer["resumable"] is False
    assert "cannot read it back" in offer["text"]
    controller.jobs.resume_offer()  # refused: it cannot be read back
    assert controller.jobs.offer == offer
    controller.jobs.discard_offer()
    assert controller.jobs.offer == {}
    assert setup.store.unfinished() == []


def test_the_header_leaves_out_the_whole_batch(setup: Setup) -> None:
    controller = setup.controller
    controller.leave_out_batch()
    assert controller.batch_left_out
    assert controller.change_count == 0
    assert not controller.can_apply
    controller.leave_out_batch()
    assert not controller.batch_left_out
    assert controller.change_count > 0


def real_statuses(mkvmerge: Path) -> Callable[[], dict[str, DependencyStatus]]:
    return lambda: {
        "mkvtoolnix": DependencyStatus("mkvtoolnix", State.FOUND, mkvmerge, version="real"),
        "ffmpeg": DependencyStatus("ffmpeg", State.MISSING),
    }


@pytest.mark.parametrize("suffix", ["", " new"])
def test_a_real_file_is_remuxed_checked_and_its_original_kept(
    qapp: QApplication, qtbot: QtBot, real_episode: Any, tmp_path: Path, suffix: str
) -> None:
    """Read-only towards everything outside `tmp_path`: the episode is made there, the original goes to the keep
    folder beside it (never the Recycle Bin), and the job store is the test's own. French audio is dropped and the
    paired Turkish subtitle file added; afterwards the window holds the new file and plans nothing more for it."""
    from showrunner.app.batches.batch import BatchKey
    from showrunner.app.library.library import LibraryLoad
    from showrunner.core.language import Language
    from showrunner.core.media import Episode, MediaItem, SubtitleFile
    from showrunner.tools.probe import probe

    programs = Programs(mkvmerge=real_episode.mkvmerge)
    item = MediaItem(
        Episode("Show Name", 1, 1),
        probe(real_episode.video, programs),
        (SubtitleFile(real_episode.subtitle, Language("tur")),),
    )
    controller = WindowController(statuses=real_statuses(real_episode.mkvmerge), jobs=JobStore(tmp_path / "j.db"))
    controller.model.add(LibraryLoad(items=(item,), roots=(real_episode.video.parent,)))
    controller.start()
    qtbot.waitUntil(lambda: controller.programs[0]["state"] != "checking")
    copy = controller.batches.copy(BatchKey.of(item))
    copy.set_options("mux", replace(copy.profile.for_stage("mux"), suffix=suffix))
    controller.select(controller.tree.index_of(str(real_episode.video)).parent())
    controller.set_original("keep")
    qtbot.waitUntil(lambda: not controller.planning)
    headers = controller.matrix["headers"]
    french = [h["id"] for h in headers if h["kind"] == "audio"][1]  # English, then French
    controller.toggle_keep(french)
    controller.toggle_keep(next(h["id"] for h in headers if h["paired"]))
    qtbot.waitUntil(lambda: not controller.planning and controller.can_apply)
    with qtbot.waitSignal(controller.jobs.ended, timeout=60_000):
        controller.apply()
    (row,) = controller.jobs.view["rows"]
    assert row["state"] == "done", row["result"]
    assert row["result"][0] == "Checked: 3 tracks, the title and the length are as planned."
    folder = real_episode.video.parent
    assert (folder / ".originals" / real_episode.video.name).exists()
    assert (folder / ".originals" / real_episode.subtitle.name).exists()
    output = real_episode.video.with_name(real_episode.video.stem + suffix + ".mkv")
    after = probe(output, programs)
    assert [t.language.alpha3 for t in after.tracks if t.language] == ["eng", "tur"]

    def read_again() -> bool:
        found = controller.model.library.item(output)
        return found is not None and [t.language.alpha3 for t in found.file.tracks if t.language] == ["eng", "tur"]

    qtbot.waitUntil(read_again, timeout=10_000)
    read = controller.model.library.item(output)
    assert read is not None
    assert read.subtitles == ()
    qtbot.waitUntil(lambda: not controller.planning)
    assert controller.change_count == 0
    controller.deleteLater()
