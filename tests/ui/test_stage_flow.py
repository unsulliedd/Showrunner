from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from showrunner.app.jobs.hashing import stamp
from showrunner.app.jobs.stages import PlanState, StagePlan, StepResult, TracksStage
from showrunner.app.jobs.store import JobStore
from showrunner.app.library.library import Library
from showrunner.app.library.loader import LibraryLoader
from showrunner.app.profiles.profile import Profile
from showrunner.app.profiles.store import ProfileStore
from showrunner.app.settings.app_settings import load_settings
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.core.track import AudioProperties, Track, TrackKind, VideoProperties
from showrunner.stages.tracks import KindTest, TrackMatch, TrackRule, Verdict
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.probe import Programs
from showrunner.ui.main_window import MainWindow
from showrunner.ui.settings import profiles
from showrunner.ui.stages.plan_view import PlannedChanges
from showrunner.ui.theme.manager import ThemeManager

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def wait_until(condition: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.005)


@dataclass(frozen=True)
class Writer:
    """Stands in for Metadata: plans a change for every file and records what it applied."""

    id: ClassVar[str] = "metadata"
    remuxes: ClassVar[bool] = False
    applied: list[str] = field(default_factory=list, repr=False, compare=False)

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        return StagePlan(self.id, PlanState.CHANGES, None, writes=True)

    def apply(self, plan: StagePlan, cancel: threading.Event | None) -> StepResult:
        self.applied.append("done")
        return StepResult(True)


def statuses() -> dict[str, DependencyStatus]:
    return {
        "mkvtoolnix": DependencyStatus("mkvtoolnix", State.MISSING),
        "ffmpeg": DependencyStatus("ffmpeg", State.MISSING),
    }


def episode(tmp_path: Path, number: int) -> MediaItem:
    path = tmp_path / "lib" / f"Show Name S01E0{number}.mkv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"matroska" * number)
    tracks = (
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080)),
        Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), audio=AudioProperties(6)),
    )
    return MediaItem(Episode("Show Name", 1, number), MediaFile(path, "matroska", tracks=tracks))


@pytest.fixture(autouse=True)
def discard_on_close(monkeypatch: pytest.MonkeyPatch) -> None:
    # A test that fails with unsaved edits must not hang on the question its window asks when it closes.
    monkeypatch.setattr(profiles, "ask_unsaved", lambda parent, name: QMessageBox.StandardButton.Discard)


@pytest.fixture
def writer() -> Writer:
    return Writer()


@pytest.fixture
def window(qapp: QApplication, theme: ThemeManager, tmp_path: Path, writer: Writer) -> MainWindow:
    loader = LibraryLoader(programs=Programs(Path("mkvmerge")))
    window = MainWindow(
        theme,
        loader,
        statuses,
        profiles=ProfileStore(tmp_path / "profiles"),
        jobs=JobStore(tmp_path / "jobs.sqlite3"),
        make_pipeline=lambda _statuses, _source: (TracksStage(), writer),
    )
    window.show()
    items = (episode(tmp_path, 1), episode(tmp_path, 2))
    window.model.set_library(Library(items, roots=(tmp_path / "lib",)))
    window.stack.setCurrentIndex(1)
    window.panel.expand_default()
    window.panel.select(window.model.index_for_path(items[0].file.path))
    return window


def run_preview(window: MainWindow) -> None:
    window.preview()
    wait_until(lambda: window.stages.preview is not None and not window.stages.busy)


def test_preview_plans_the_batch_and_names_its_reach(window: MainWindow) -> None:
    assert window.stage_bar.apply.text() == "Apply"
    run_preview(window)
    assert window.stages.is_current
    assert window.stage_bar.apply.text() == "Apply to 2 files"
    assert window.stage_bar.apply.isEnabled()
    assert window.stage_bar.stamp.text().startswith("Preview of 2 videos")
    assert window.summary.texts()[:2] == ["Preview of 2 videos", "· 2 change"]
    path = window.stages.preview.files[0].item.file.path
    assert window.model.dot(path) == "control"
    assert window.sheet.state.text() == "Changes planned"


def test_a_change_of_options_makes_the_preview_out_of_date(window: MainWindow) -> None:
    run_preview(window)
    window.session.update("tracks", enabled=True)
    assert not window.stages.is_current
    assert not window.stage_bar.apply.isEnabled()
    assert window.stage_bar.stamp.text() == "Options changed since the preview"
    window.session.revert()
    assert window.stages.is_current


def test_a_change_of_the_library_makes_the_preview_out_of_date(window: MainWindow, tmp_path: Path) -> None:
    run_preview(window)
    window.model.set_library(Library((episode(tmp_path, 3),)))
    assert not window.stages.is_current


def test_apply_runs_the_job_after_one_question(window: MainWindow, writer: Writer) -> None:
    asked: list[tuple[int, int]] = []
    window.confirm_apply = lambda files, remuxed: asked.append((files, remuxed)) or True  # type: ignore[method-assign]
    run_preview(window)
    window.apply()
    wait_until(lambda: len(writer.applied) == 2 and not window.stages.busy)
    assert asked == [(2, 0)]
    assert window.stages.preview is None
    assert window.stages.store.unfinished() == []


def test_a_left_out_file_is_not_applied(window: MainWindow, writer: Writer) -> None:
    window.confirm_apply = lambda files, remuxed: True  # type: ignore[method-assign]
    run_preview(window)
    window.stages.leave_out(window.stages.preview.files[0].item.file.path, True)
    assert window.stage_bar.apply.text() == "Apply to 1 file"
    window.apply()
    wait_until(lambda: len(writer.applied) == 1 and not window.stages.busy)


def test_a_template_problem_blocks_metadata_and_says_where(window: MainWindow) -> None:
    window.session.update("naming", audio_track_template="{nope}")
    switch = window.stage_bar.switches["metadata"]
    assert switch.toolTip() == "Not planned: its options have 1 problem."
    run_preview(window)
    plan = window.stages.preview.files[0].plan_for("metadata")
    assert plan is not None
    assert plan.state is PlanState.BLOCKED
    assert window.summary.texts()[-1] == "· Metadata not planned: 1 problem in Naming"
    window.session.revert()


def test_a_refused_plan_needs_a_look_and_keeps_the_other_stages(window: MainWindow) -> None:
    drop_audio = TrackRule(match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.DROP)
    window.session.update("tracks", enabled=True, rules=[drop_audio])
    run_preview(window)
    file = window.stages.preview.files[0]
    assert file.outcome.value == "refused"
    assert [p.stage for p in file.writes] == ["metadata"]
    assert window.model.dot(file.item.file.path) == "accent_ink"
    assert window.model.needs_look_count() == 2
    assert window.sheet.state.text() == "Tracks refused"
    window.session.revert()


def test_unfinished_jobs_are_offered_once_the_programs_are_known(window: MainWindow, tmp_path: Path) -> None:
    store = window.stages.store
    item = episode(tmp_path, 4)
    job = store.create("key", window.session.profile, [(item, stamp(item.file.path), Writer().plan(item, None))])  # type: ignore[arg-type]
    answers: list[int] = []
    window.ask_resume = lambda summary: answers.append(summary.id) or "discard"  # type: ignore[method-assign]
    window.offer_unfinished_jobs()
    wait_until(lambda: answers == [job])
    assert store.unfinished() == []


def test_an_unresumable_job_is_offered_for_discard_only(window: MainWindow, tmp_path: Path) -> None:
    store = window.stages.store
    item = episode(tmp_path, 5)
    job = store.create("key", window.session.profile, [(item, stamp(item.file.path), Writer().plan(item, None))])  # type: ignore[arg-type]
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        connection.execute("UPDATE jobs SET app_version = '0.0.0' WHERE id = ?", (job,))
    offered: list[int] = []
    window.ask_resume = lambda summary: pytest.fail("an unresumable job cannot be resumed")  # type: ignore[method-assign]
    window.ask_discard_unresumable = lambda summary: offered.append(summary.id) or True  # type: ignore[method-assign]
    window.offer_unfinished_jobs()
    wait_until(lambda: offered == [job])
    assert store.unfinished() == []


def test_a_broken_rule_blocks_tracks_with_a_way_to_the_rule(window: MainWindow) -> None:
    rule = TrackRule(label="Keep", match=TrackMatch(languages=["egn"]), verdict=Verdict.KEEP)
    window.session.update("tracks", enabled=True, rules=[rule])
    run_preview(window)
    path = window.stages.preview.files[0].item.file.path
    window.panel.select(window.model.index_for_path(path))
    plan = window.sheet.findChild(PlannedChanges)
    assert plan is not None
    assert plan.texts[0] == "Not planned for any file: rule 1 has a problem."
    opened: list[int] = []
    plan.open_rule.disconnect()
    plan.open_rule.connect(opened.append)
    plan.open_rule.emit(0)
    assert opened == [0]
    window.session.revert()


def test_closing_with_unsaved_changes_asks_first(window: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    window.session.update("tracks", enabled=True)
    monkeypatch.setattr(profiles, "ask_unsaved", lambda parent, name: QMessageBox.StandardButton.Cancel)
    assert not window.close()
    assert window.isVisible()
    monkeypatch.setattr(profiles, "ask_unsaved", lambda parent, name: QMessageBox.StandardButton.Discard)
    assert window.close()


def test_the_workspace_comes_back_at_the_next_start(window: MainWindow, theme: ThemeManager, tmp_path: Path) -> None:
    selected = window.model.library.items[1].file.path
    window.panel.select(window.model.index_for_path(selected))
    assert window.close()
    settings = load_settings().value
    assert (settings.last_folders, settings.last_selection) == ([str(tmp_path / "lib")], str(selected))
    later = MainWindow(theme, reader_statuses=statuses, jobs=JobStore(tmp_path / "jobs.sqlite3"))
    started: list[list[Path]] = []
    later.add_paths = started.append  # type: ignore[method-assign]
    later.restore_workspace()
    assert started == [[tmp_path / "lib"]]
    assert later._restore_selection == selected
