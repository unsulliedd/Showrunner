"""Apply: a current preview becomes a stored job, and the job runs one step at a time. The same run resumes a job
that was interrupted."""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from showrunner.app.jobs.hashing import stamp
from showrunner.app.jobs.preview import Preview
from showrunner.app.jobs.stages import PlanState, Stage
from showrunner.app.jobs.store import FINAL, JobStore, StepState, StoredStep
from showrunner.app.profiles.profile import Profile
from showrunner.core.media import MediaFile
from showrunner.tools.process import ProcessCancelledError

Progress = Callable[[int, int], None]  # steps finished, steps in the job
Read = Callable[[Path], MediaFile]  # reads a file's tracks again, as the library load does


class StalePreviewError(Exception):
    """The options, the stages or the blocked stages changed since the preview."""


@dataclass(frozen=True, slots=True)
class StepRecord:
    position: int
    path: Path
    stage: str
    state: StepState
    message: str = ""
    # The stage's own result (`ApplyResult` for Metadata) for a step run by this call; None otherwise, since only
    # the state and the message are stored.
    detail: object = None


@dataclass(frozen=True, slots=True)
class JobResult:
    job_id: int
    steps: tuple[StepRecord, ...]
    cancelled: bool = False


def create_job(
    store: JobStore,
    preview: Preview,
    profile: Profile,
    stages: Sequence[Stage],
    *,
    blocked: Collection[str] = (),
) -> int:
    """Store one step per plan that writes, in file order and then pipeline order. `profile`, `stages` and
    `blocked` are the current ones; a preview made with others raises `StalePreviewError`."""
    if not preview.is_current(profile, stages, blocked):
        raise StalePreviewError("the options changed since the preview")
    steps = [(f.item, f.stamp, plan) for f in preview.files if f.stamp is not None for plan in f.writes]
    return store.create(preview.options_key, preview.profile, steps)


def run_job(
    store: JobStore,
    job_id: int,
    stages: Sequence[Stage],
    *,
    read: Read,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> JobResult:
    """Run every step that has not finished. A file whose stamp differs from the preview is not written. A step
    that was running when the app stopped is checked against the file read again: done when the file already
    shows it, run again when the file is as it was planned, stale otherwise."""
    job = store.load(job_id)
    by_id = {stage.id: stage for stage in stages}
    states = {step.position: (step.state, step.message) for step in job.steps}
    details: dict[int, object] = {}
    cancelled = False

    def record(step: StoredStep, state: StepState, message: str = "") -> None:
        store.set_state(job_id, step.position, state, message)
        states[step.position] = (state, message)

    def attempt(step: StoredStep) -> tuple[StepState, str, object]:
        earlier = [states[s.position][0] for s in job.steps if s.path == step.path and s.position < step.position]
        if any(state is not StepState.DONE for state in earlier):
            return StepState.SKIPPED, "", None
        stage = by_id.get(step.plan.stage)
        if stage is None:
            return StepState.FAILED, f"stage {step.plan.stage!r} is not available", None
        if step.state is StepState.RUNNING:
            verdict, message = _recheck(step, stage, job.profile, read)
        elif not earlier:
            # Only the file's first step can compare stamps: each step that writes changes them.
            verdict, message = _check_stamp(step)
        else:
            verdict, message = None, ""
        if verdict is not None:
            return verdict, message, None
        record(step, StepState.RUNNING)
        try:
            result = stage.apply(step.plan, cancel)
        except ProcessCancelledError:
            raise
        except Exception as error:  # one file's failure never stops the batch
            return StepState.FAILED, str(error) or type(error).__name__, None
        return StepState.DONE if result.ok else StepState.FAILED, result.message, result.detail

    for step in job.steps:
        if step.state in FINAL:
            continue
        if cancel is not None and cancel.is_set():
            cancelled = True
            break
        try:
            state, message, details[step.position] = attempt(step)
        except ProcessCancelledError:
            cancelled = True  # the step keeps its state, so a resume checks what it wrote
            break
        record(step, state, message)
        if all(states[s.position][0] is StepState.DONE for s in job.steps if s.path == step.path):
            _mark_finished(store, job.options_key, step.path)
        if progress is not None:
            progress(sum(state in FINAL for state, _ in states.values()), len(job.steps))

    records = tuple(
        StepRecord(s.position, s.path, s.plan.stage, *states[s.position], details.get(s.position)) for s in job.steps
    )
    return JobResult(job_id, records, cancelled)


def _check_stamp(step: StoredStep) -> tuple[StepState | None, str]:
    try:
        current = stamp(step.path)
    except OSError as error:
        return StepState.STALE, str(error)
    return (None, "") if current == step.stamp else (StepState.STALE, "")


def _recheck(step: StoredStep, stage: Stage, profile: Profile, read: Read) -> tuple[StepState | None, str]:
    try:
        file = read(step.path)
    except ProcessCancelledError:
        raise
    except Exception as error:  # the file cannot be checked, so it is not written
        return StepState.FAILED, str(error) or type(error).__name__
    fresh = stage.plan(replace(step.item, file=file), profile)
    if fresh.state is PlanState.UNCHANGED:
        return StepState.DONE, ""
    return (None, "") if fresh == step.plan else (StepState.STALE, "")


def _mark_finished(store: JobStore, options_key: str, path: Path) -> None:
    try:
        after = stamp(path)
    except OSError:
        return  # moved away already; it is only not recognized later
    store.mark_finished(after.content_hash, options_key)
