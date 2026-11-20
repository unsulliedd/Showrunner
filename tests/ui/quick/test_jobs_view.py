"""What the drawer's Jobs tab draws of a job: steps by phase, times, and each file's result in words."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from showrunner.app.jobs.hashing import FileStamp
from showrunner.app.jobs.run import JobResult, StepRecord
from showrunner.app.jobs.stages import PlanState, StagePlan
from showrunner.app.jobs.store import StepState, StoredJob, StoredStep
from showrunner.app.profiles.profile import Profile
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.stages.metadata.apply import ApplyResult
from showrunner.stages.mux import Failure, MuxResult, VerifyProblem
from showrunner.ui.quick.jobs import JobProgress, check_text, clock, mux_text, reason_text

A, B, C = Path("a.mkv"), Path("b.mkv"), Path("c.mkv")


def step(position: int, path: Path, stage: str, state: StepState = StepState.PENDING) -> StoredStep:
    item = MediaItem(Movie(path.stem), MediaFile(path, "matroska"))
    return StoredStep(position, item, FileStamp(1, 1, "x"), StagePlan(stage, PlanState.CHANGES, writes=True), state)


def progress(*steps: StoredStep) -> JobProgress:
    job = StoredJob(1, 0.0, "key", Profile.defaults("Test"), steps)
    return JobProgress(job, "Season 1", datetime(2026, 1, 1, 21, 4), lambda path: ("", path.stem))


def record(position: int, path: Path, stage: str, state: StepState, detail: object = None) -> StepRecord:
    return StepRecord(position, path, stage, state, "", detail)


def test_a_remux_moves_through_its_phases_and_ends_worded() -> None:
    job = progress(step(0, A, "mux"), step(1, B, "mux"), step(2, C, "metadata"))
    job.step_changed(record(0, A, "mux", StepState.RUNNING), 0.0)
    job.step_progress(A, "mux", 0.64)
    view = job.view(76.0)
    first = view["rows"][0]
    assert [(p["label"], p["state"], p["percent"]) for p in first["phases"]] == [
        ("Write new file", "active", 64),
        ("Check", "waiting", -1),
        ("Move original", "waiting", -1),
        ("Take its name", "waiting", -1),
    ]
    assert (first["state"], first["time"]) == ("running", "1:16 so far")
    assert view["rows"][1]["time"] == "waiting"
    assert (view["title"], view["started"], view["count"]) == ("Apply · Season 1", "started 21:04", "0 of 3")
    assert round(view["fraction"], 2) == round(0.64 / 3, 2)
    job.step_progress(A, "mux", 1.0)
    assert [p["state"] for p in job.view(80.0)["rows"][0]["phases"]][:2] == ["done", "active"]
    job.step_changed(record(0, A, "mux", StepState.DONE, MuxResult(A, recycled=(A,))), 118.0)
    assert job.view(118.0)["rows"][0]["time"] == "1:58"
    assert job.view(118.0)["line"] == "1 of 3 · about 4 minutes left"
    job.step_changed(record(1, B, "mux", StepState.RUNNING), 118.0)
    problems = (VerifyProblem("duration", planned="3134.000", found="12.000"),)
    job.step_changed(record(1, B, "mux", StepState.FAILED, MuxResult(failure=Failure.VERIFY, problems=problems)), 130.0)
    job.step_changed(record(2, C, "metadata", StepState.RUNNING), 130.0)
    job.step_changed(record(2, C, "metadata", StepState.DONE, ApplyResult()), 131.0)
    job.finish(JobResult(1, ()), 131.0)
    rows = job.view(131.0)["rows"]
    assert [p["state"] for p in rows[1]["phases"]] == ["done", "failed", "waiting", "waiting"]
    assert rows[1]["result"] == [
        "The new file did not pass its check, so it was removed. The original was not touched.",
        "The new file lasts 12.000 s; the original 3134.000 s.",
    ]
    assert [(p["label"], p["state"]) for p in rows[2]["phases"]] == [("Edit in place", "done")]
    assert rows[2]["result"] == ["Edited in place and read back as planned."]
    assert job.view(131.0)["summary"] == "2 done, 1 failed, 0 not written."


def test_stale_skipped_and_cancelled_files_say_why_nothing_was_written() -> None:
    job = progress(step(0, A, "mux"), step(1, B, "mux"), step(2, C, "mux"))
    job.step_changed(record(0, A, "mux", StepState.STALE), 1.0)
    job.step_changed(record(1, B, "mux", StepState.SKIPPED), 1.0)
    job.step_changed(record(2, C, "mux", StepState.RUNNING), 1.0)
    job.finish(JobResult(1, (), cancelled=True), 2.0)
    rows = job.view(2.0)["rows"]
    assert [r["state"] for r in rows] == ["stale", "skipped", "stopped"]
    assert rows[0]["result"] == ["The file changed since it was planned, so it was not written."]
    assert rows[1]["result"] == ["Not written: an earlier step of this file did not finish."]
    assert rows[2]["result"][0].startswith("Stopped by Cancel. The original was not touched")
    assert [p["state"] for p in rows[2]["phases"]] == ["stopped", "waiting", "waiting", "waiting"]
    assert job.view(2.0)["summary"].startswith("Cancelled. 0 done, 0 failed, 3 not written.")


def test_failures_and_checks_are_worded() -> None:
    assert check_text(VerifyProblem("tracks", planned="6", found="5")) == "The new file has 5 tracks; 6 were planned."
    assert check_text(VerifyProblem("name", 0, "English", "")) == "Track 1: the name is none; English was planned."
    assert check_text(VerifyProblem("read", found="mkvmerge")) == "The new file could not be read back: mkvmerge."
    assert check_text(VerifyProblem("chapters", planned="8", found="0")) == (
        "The new file has 0 chapters; the original has 8."
    )
    assert mux_text(None, MuxResult(failure=Failure.MERGE, detail="disk full")) == [
        "MKVToolNix could not write the new file: disk full. The original was not touched."
    ]
    kept = MuxResult(A, kept=(Path(".originals") / "a.mkv",), left=(Path("a.tr.srt"),), resumed=True)
    assert mux_text(None, kept)[1:] == [
        "The original is in .originals.",
        "a.tr.srt stays beside the video: it changed while the new file was written.",
        "Finished after a restart.",
    ]
    assert (clock(5), clock(3723)) == ("0:05", "1:02:03")


def test_a_stored_failure_is_worded_and_any_other_message_is_kept() -> None:
    assert reason_text("missed: 1/2") == "1 of 2 changes were not in the file when it was read back after the edit."
    assert reason_text("merge: disk full") == (
        "MKVToolNix could not write the new file: disk full. The original was not touched."
    )
    assert reason_text("exit code 2") == "exit code 2"
    job = progress(step(0, A, "metadata"))
    job.step_changed(StepRecord(0, A, "metadata", StepState.FAILED, "missed: 1/2"), 1.0)  # as read back from the store
    assert job.view(2.0)["rows"][0]["result"] == [
        "Not written: 1 of 2 changes were not in the file when it was read back after the edit."
    ]
