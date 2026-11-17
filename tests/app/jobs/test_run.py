from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.app.jobs.hashing import stamp
from showrunner.app.jobs.preview import FileOutcome, preview, preview_each
from showrunner.app.jobs.run import JobResult, StalePreviewError, create_job, run_job
from showrunner.app.jobs.stages import MetadataStage, Stage, StagePlan, StepResult, TracksStage
from showrunner.app.jobs.store import JobStore, StepState, UnresumableJobError
from showrunner.app.jobs.worker import JobRunner
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.track import AudioProperties, Track, TrackKind, VideoProperties
from showrunner.stages.tracks import TracksOptions
from showrunner.tools.probe import Programs
from showrunner.tools.process import ProcessCancelledError


def start(store: JobStore, profile: Profile, stages: tuple[Stage, ...], items: list[MediaItem]) -> int:
    return create_job(store, preview(items, profile, stages), profile, stages)


def states(result: JobResult) -> dict[str, StepState]:
    return {record.path.name: record.state for record in result.steps}


def text(item: MediaItem) -> str:
    return item.file.path.read_text(encoding="utf-8")


def test_apply_writes_each_file_and_records_it(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    stage = files.FakeStage()
    items = [files.item("a.mkv"), files.item("b.mkv"), files.item("c.mkv", "plain+edited")]
    job = start(store, profile, (stage,), items)
    progress: list[tuple[int, int]] = []
    result = run_job(store, job, (stage,), read=files.read, progress=lambda *p: progress.append(p))
    assert states(result) == {"a.mkv": StepState.DONE, "b.mkv": StepState.DONE}  # c.mkv had nothing to do
    assert stage.applied == ["a.mkv", "b.mkv"]
    assert progress == [(1, 2), (2, 2)]
    assert not result.cancelled
    assert store.unfinished() == []


def test_a_renamed_finished_file_is_recognized(
    files: SimpleNamespace, store: JobStore, profile: Profile, tmp_path: Path
) -> None:
    stage = files.FakeStage()
    item = files.item("a.mkv")
    run_job(store, start(store, profile, (stage,), [item]), (stage,), read=files.read)
    moved = tmp_path / "elsewhere" / "renamed.mkv"
    moved.parent.mkdir()
    item.file.path.rename(moved)
    again = preview([MediaItem(item.identity, files.read(moved))], profile, (stage,), finished=store.is_finished)
    assert again.files[0].finished_before
    assert again.files[0].outcome is FileOutcome.UNCHANGED
    other = preview([MediaItem(item.identity, files.read(moved))], profile, (), finished=store.is_finished)
    assert not other.files[0].finished_before  # other stages: another options key


def test_a_file_changed_after_the_preview_is_not_written(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stage = files.FakeStage()
    first, second = files.item("a.mkv"), files.item("b.mkv")
    job = start(store, profile, (stage,), [first, second])
    first.file.path.write_text("edited elsewhere", encoding="utf-8")
    result = run_job(store, job, (stage,), read=files.read)
    assert states(result) == {"a.mkv": StepState.STALE, "b.mkv": StepState.DONE}
    assert text(first) == "edited elsewhere"


def test_a_failure_marks_its_file_and_the_batch_goes_on(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stage = files.FakeStage()
    job = start(store, profile, (stage,), [files.item("a.mkv", "will fail"), files.item("b.mkv")])
    result = run_job(store, job, (stage,), read=files.read)
    assert states(result) == {"a.mkv": StepState.FAILED, "b.mkv": StepState.DONE}
    assert result.steps[0].message == "disk full"


def test_each_step_is_told_as_it_starts_and_ends(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    profile = profile.with_options("tracks", TracksOptions())
    stages = (files.FakeStage(), files.SecondStage())
    job = start(store, profile, stages, [files.item("a.mkv", "will fail"), files.item("b.mkv")])
    told: list[tuple[str, str, StepState, str]] = []
    run_job(
        store,
        job,
        stages,
        read=files.read,
        step_changed=lambda r: told.append((r.path.name, r.stage, r.state, r.message)),
    )
    # A skipped step never runs, so it is told only as it ends.
    assert told == [
        ("a.mkv", "metadata", StepState.RUNNING, ""),
        ("a.mkv", "metadata", StepState.FAILED, "disk full"),
        ("a.mkv", "tracks", StepState.SKIPPED, ""),
        ("b.mkv", "metadata", StepState.RUNNING, ""),
        ("b.mkv", "metadata", StepState.DONE, ""),
        ("b.mkv", "tracks", StepState.RUNNING, ""),
        ("b.mkv", "tracks", StepState.DONE, ""),
    ]


def test_later_steps_of_a_file_whose_step_failed_are_skipped(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    profile = profile.with_options("tracks", TracksOptions())
    stages = (files.FakeStage(), files.SecondStage())
    job = start(store, profile, stages, [files.item("a.mkv", "will fail")])
    result = run_job(store, job, stages, read=files.read)
    assert [(r.stage, r.state) for r in result.steps] == [
        ("metadata", StepState.FAILED),
        ("tracks", StepState.SKIPPED),
    ]


def test_a_preview_made_with_other_options_is_refused(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stage = files.FakeStage()
    made = preview([files.item("a.mkv")], profile, (stage,))
    with pytest.raises(StalePreviewError):
        create_job(store, made, profile.with_options("tracks", TracksOptions(flags_from_names=False)), (stage,))
    with pytest.raises(StalePreviewError):
        create_job(store, made, profile, (stage,), blocked={"metadata"})


def test_each_file_keeps_its_own_options_in_the_job(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    """A season whose episode chose otherwise: each file is planned, stored and marked finished with its options."""
    stage = files.FakeStage()
    a, b = files.item("a.mkv"), files.item("b.mkv")
    other = profile.with_options("tracks", TracksOptions(flags_from_names=False))
    profiles = {a.file.path: profile, b.file.path: other}
    made = preview_each([a, b], profiles, (stage,))
    assert made.files[0].options_key != made.files[1].options_key
    with pytest.raises(StalePreviewError):
        create_job(store, made, dict.fromkeys(profiles, profile), (stage,))
    job = store.load(create_job(store, made, profiles, (stage,)))
    assert [job.profile_of(s).for_stage("tracks").flags_from_names for s in job.steps] == [True, False]
    run_job(store, job.id, (stage,), read=files.read)
    for file in made.files:
        assert store.is_finished(stamp(file.item.file.path).content_hash, file.options_key)


def test_a_needs_remux_or_missing_file_gets_no_step(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    stage = files.FakeStage()
    gone = files.item("gone.mkv")
    gone.file.path.unlink()
    made = preview([gone, files.item("refuse.mkv", "refuse")], profile, (stage,))
    assert [f.outcome for f in made.files] == [FileOutcome.MISSING, FileOutcome.REFUSED]
    job = create_job(store, made, profile, (stage,))
    assert store.load(job).steps == ()


@pytest.mark.parametrize(
    ("after_write", "applied_on_resume"),
    [(False, ["b.mkv", "c.mkv"]), (True, ["c.mkv"])],
    ids=["killed-before-write", "killed-after-write"],
)
def test_a_job_killed_mid_batch_resumes_where_it_stopped(
    files: SimpleNamespace,
    store: JobStore,
    profile: Profile,
    tmp_path: Path,
    after_write: bool,
    applied_on_resume: list[str],
) -> None:
    items = [files.item("a.mkv"), files.item("b.mkv"), files.item("c.mkv")]
    crashing = files.FakeStage(crash_on="b.mkv", crash_after_write=after_write)
    job = start(store, profile, (crashing,), items)
    with pytest.raises(files.Killed):
        run_job(store, job, (crashing,), read=files.read)
    assert crashing.applied == ["a.mkv"]

    # A new process: a fresh store on the same file, the job read back from disk.
    reopened = JobStore(tmp_path / "data" / "jobs.sqlite3")
    (summary,) = reopened.unfinished()
    assert (summary.id, summary.steps, summary.finished) == (job, 3, 1)
    assert [s.state for s in reopened.load(job).steps] == [StepState.DONE, StepState.RUNNING, StepState.PENDING]

    stage = files.FakeStage()
    result = run_job(reopened, job, (stage,), read=files.read)
    assert stage.applied == applied_on_resume
    assert set(states(result).values()) == {StepState.DONE}
    assert [text(i) for i in items] == ["plain+edited"] * 3  # nothing written twice
    assert reopened.unfinished() == []


def test_an_interrupted_file_changed_since_is_stale(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    item = files.item("a.mkv")
    crashing = files.FakeStage(crash_on="a.mkv")
    job = start(store, profile, (crashing,), [item])
    with pytest.raises(files.Killed):
        run_job(store, job, (crashing,), read=files.read)
    item.file.path.write_text("other", encoding="utf-8")
    stage = files.FakeStage()
    assert states(run_job(store, job, (stage,), read=files.read)) == {"a.mkv": StepState.STALE}
    assert stage.applied == []


def test_cancel_stops_between_files_and_the_job_resumes(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stage = files.FakeStage()
    job = start(store, profile, (stage,), [files.item("a.mkv"), files.item("b.mkv")])
    cancel = threading.Event()
    result = run_job(store, job, (stage,), read=files.read, progress=lambda *_: cancel.set(), cancel=cancel)
    assert result.cancelled
    assert states(result) == {"a.mkv": StepState.DONE, "b.mkv": StepState.PENDING}
    assert len(store.unfinished()) == 1
    assert states(run_job(store, job, (stage,), read=files.read)) == {"a.mkv": StepState.DONE, "b.mkv": StepState.DONE}


@pytest.mark.parametrize("during", ["apply", "recheck"])
def test_a_cancelled_program_leaves_its_step_to_be_checked(
    files: SimpleNamespace, store: JobStore, profile: Profile, during: str
) -> None:
    @dataclass(frozen=True)
    class Cancelled(files.FakeStage):  # type: ignore[misc, name-defined]
        def apply(self, plan: StagePlan, cancel: threading.Event | None, progress: object = None) -> StepResult:
            raise ProcessCancelledError("cancelled", ())

    def cancelled_read(path: Path) -> MediaFile:
        raise ProcessCancelledError("cancelled", ())

    item = files.item("a.mkv")
    job = start(store, profile, (Cancelled(),), [item, files.item("b.mkv")])
    result = run_job(store, job, (Cancelled(),), read=files.read)
    assert result.cancelled
    assert states(result) == {"a.mkv": StepState.RUNNING, "b.mkv": StepState.PENDING}
    if during == "recheck":
        assert run_job(store, job, (files.FakeStage(),), read=cancelled_read).cancelled
        assert store.load(job).steps[0].state is StepState.RUNNING
    stage = files.FakeStage()
    assert set(states(run_job(store, job, (stage,), read=files.read)).values()) == {StepState.DONE}
    assert stage.applied == ["a.mkv", "b.mkv"]


def test_skipped_and_failed_steps_count_for_progress(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    job = start(store, profile, (files.FakeStage(),), [files.item("a.mkv"), files.item("b.mkv")])
    progress: list[tuple[int, int]] = []
    run_job(store, job, (), read=files.read, progress=lambda *p: progress.append(p))
    assert progress == [(1, 2), (2, 2)]


def test_a_job_can_be_discarded(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    job = start(store, profile, (files.FakeStage(),), [files.item("a.mkv")])
    store.discard(job)
    assert store.unfinished() == []
    with pytest.raises(KeyError):
        store.load(job)


def test_a_stage_that_is_gone_fails_its_steps(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    job = start(store, profile, (files.FakeStage(),), [files.item("a.mkv")])
    result = run_job(store, job, (), read=files.read)
    assert states(result) == {"a.mkv": StepState.FAILED}
    assert "not available" in result.steps[0].message


def test_a_job_that_cannot_be_read_back_is_reported(
    files: SimpleNamespace, store: JobStore, profile: Profile, tmp_path: Path
) -> None:
    job = start(store, profile, (files.FakeStage(),), [files.item("a.mkv")])
    with sqlite3.connect(tmp_path / "data" / "jobs.sqlite3") as connection:
        connection.execute("UPDATE steps SET plan = ?", (b"not a pickle",))
    connection.close()
    with pytest.raises(UnresumableJobError):
        store.load(job)


def test_a_job_stored_by_another_version_is_not_resumed(
    files: SimpleNamespace, store: JobStore, profile: Profile, tmp_path: Path
) -> None:
    job = start(store, profile, (files.FakeStage(),), [files.item("a.mkv")])
    with sqlite3.connect(tmp_path / "data" / "jobs.sqlite3") as connection:
        connection.execute("UPDATE jobs SET app_version = ?", ("0.0.0",))
    connection.close()
    with pytest.raises(UnresumableJobError, match="version"):
        store.load(job)


def test_real_plans_survive_the_round_trip(tmp_path: Path, store: JobStore, profile: Profile) -> None:
    path = tmp_path / "Movie.mkv"
    path.write_bytes(b"matroska")
    tracks = (
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080, 23.976)),
        Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), audio=AudioProperties(6)),
    )
    item = MediaItem(Movie("Movie"), MediaFile(path, "matroska", tracks=tracks))
    stages = (TracksStage(), MetadataStage(Path("mkvpropedit"), Programs()))
    made = preview([item], profile, stages)
    (step,) = store.load(create_job(store, made, profile, stages)).steps
    assert step.item == item
    assert step.plan == made.files[0].writes[0]
    assert step.stamp == made.files[0].stamp


def wait_until(condition: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.005)


def test_the_runner_reports_on_the_calling_thread(
    qapp: QApplication, files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stage = files.FakeStage()
    job = start(store, profile, (stage,), [files.item("a.mkv"), files.item("b.mkv")])
    runner = JobRunner(store, (stage,), files.read)
    progress: list[tuple[int, int]] = []
    results: list[JobResult] = []
    runner.progress.connect(lambda done, total: progress.append((done, total)))
    runner.finished.connect(results.append)
    runner.start(job)
    assert runner.busy
    wait_until(lambda: bool(results))
    assert not runner.busy
    assert progress == [(1, 2), (2, 2)]
    assert states(results[0]) == {"a.mkv": StepState.DONE, "b.mkv": StepState.DONE}


def test_a_job_stored_before_tracks_had_an_order_is_not_resumed(
    files: SimpleNamespace, store: JobStore, profile: Profile, tmp_path: Path
) -> None:
    """Its track plans were pickled without `TrackPlan.reordered`, so they are refused, and offered to discard."""
    job = start(store, profile, (files.FakeStage(),), [files.item("a.mkv")])
    with sqlite3.connect(tmp_path / "data" / "jobs.sqlite3") as connection:
        connection.execute("UPDATE jobs SET app_version = ?", ("0.1.4",))
    connection.close()
    with pytest.raises(UnresumableJobError, match=r"0.1.4"):
        store.load(job)
    assert [j.id for j in store.unfinished()] == [job]
