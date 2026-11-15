"""The Jobs tab of the drawer and the top bar while Apply runs: each file's steps as the stages run them, and each
file's result in words, the remux check included.

`JobProgress` is plain Python: it is told of each step as it starts and ends and of the fraction of a long step, and
builds what QML draws. `Jobs` runs one job at a time through the app layer's `JobRunner` on a pool thread and feeds
it; the runner's signals reach `Jobs` queued, so every update happens on the GUI thread.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from showrunner.app.jobs.run import JobResult, Read, StepRecord
from showrunner.app.jobs.stages import Stage
from showrunner.app.jobs.store import FINAL, JobStore, JobSummary, StepState, StoredJob, UnresumableJobError
from showrunner.app.jobs.worker import JobRunner
from showrunner.stages.metadata.apply import ApplyResult
from showrunner.stages.mux import Failure, MuxPlan, MuxResult, VerifyProblem
from showrunner.ui.i18n.catalog import tr, tr_plural

_log = logging.getLogger(__name__)

# The steps a file goes through inside one stage's step, as the drawer names them. A remux is the mux stage's own
# order: the original moves only after the new file passed its check.
PHASES: dict[str, tuple[str, ...]] = {"mux": ("write", "check", "original", "rename"), "metadata": ("edit",)}
# Where a remux stopped, by the phase that failed.
_FAILED_PHASE = {
    Failure.OUTPUT_EXISTS: "write",
    Failure.MERGE: "write",
    Failure.VERIFY: "check",
    Failure.DISPOSE: "original",
    Failure.RENAME: "rename",
    Failure.STALE: "write",
}
REFRESH_MS = 1000  # how often the elapsed times of a running job are drawn again


def clock(seconds: float) -> str:
    """ "1:58", "1:02:03"."""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"


def check_text(problem: VerifyProblem) -> str:
    """One way the new file differs from the plan, in words."""
    if problem.what in ("read", "tracks", "title", "duration"):
        return tr(f"jobs.check.{problem.what}", planned=problem.planned, found=problem.found or tr("jobs.check.none"))
    return tr(
        "jobs.check.track",
        number=problem.position + 1,
        what=tr(f"jobs.check.what.{problem.what}"),
        planned=problem.planned or tr("jobs.check.none"),
        found=problem.found or tr("jobs.check.none"),
    )


def mux_text(plan: MuxPlan | None, result: MuxResult) -> list[str]:
    """What a remux did or why it stopped, and where the original is now."""
    if result.ok:
        tracks = len(plan.tracks) if plan is not None else 0
        lines = [tr_plural("jobs.result.checked", tracks)]
        if result.recycled:
            lines.append(tr("jobs.result.recycled"))
        if result.kept:
            lines.append(tr("jobs.result.kept", folder=result.kept[0].parent.name))
        lines += [tr("jobs.result.left", name=path.name) for path in result.left]
        if result.resumed:
            lines.append(tr("jobs.result.resumed"))
        return lines
    assert result.failure is not None
    lines = [tr(f"jobs.failure.{result.failure.value}", detail=result.detail)]
    lines += [check_text(problem) for problem in result.problems]
    return lines


@dataclass
class FileRun:
    """One file of the job: its steps by position, in order."""

    path: Path
    number: str
    title: str
    steps: list[int]
    started: float | None = None
    ended: float | None = None


@dataclass
class JobProgress:
    """What the drawer shows of one job. Times come from the caller's clock, so the state can be tested."""

    job: StoredJob
    name: str  # what is applied: the batch, or an earlier job by its profile
    started: datetime
    names: Callable[[Path], tuple[str, str]]  # a file's number and title for its row
    states: dict[int, StepState] = field(default_factory=dict)
    records: dict[int, StepRecord] = field(default_factory=dict)
    fractions: dict[int, float] = field(default_factory=dict)
    files: list[FileRun] = field(default_factory=list)
    result: JobResult | None = None
    failed: str = ""  # the error that stopped the whole job, if one did

    def __post_init__(self) -> None:
        by_path: dict[Path, FileRun] = {}
        for step in self.job.steps:
            self.states[step.position] = step.state
            if step.path not in by_path:
                by_path[step.path] = FileRun(step.path, *self.names(step.path), [])
                self.files.append(by_path[step.path])
            by_path[step.path].steps.append(step.position)

    @property
    def running(self) -> bool:
        return self.result is None and not self.failed

    def _file(self, path: Path) -> FileRun | None:
        return next((f for f in self.files if f.path == path), None)

    def step_changed(self, record: StepRecord, now: float) -> None:
        self.states[record.position] = record.state
        file = self._file(record.path)
        if record.state is StepState.RUNNING:
            self.fractions[record.position] = 0.0
            if file is not None and file.started is None:
                file.started = now
            return
        self.records[record.position] = record
        if file is not None and all(self.states[p] in FINAL for p in file.steps):
            file.ended = now

    def step_progress(self, path: Path, stage: str, fraction: float) -> None:
        file = self._file(path)
        running = [p for p in (file.steps if file else ()) if self.states[p] is StepState.RUNNING]
        if running:
            self.fractions[running[0]] = fraction

    def finish(self, result: JobResult, now: float) -> None:
        self.result = result
        for record in result.steps:
            self.states.setdefault(record.position, record.state)
        for file in self.files:
            if file.started is not None and file.ended is None:
                file.ended = now

    # What QML draws

    def done_steps(self) -> float:
        """Finished steps, with the running ones' fractions."""
        return sum(
            1.0 if state in FINAL else self.fractions.get(p, 0.0) if state is StepState.RUNNING else 0.0
            for p, state in self.states.items()
        )

    def view(self, now: float) -> dict[str, Any]:
        total = len(self.files)
        done = sum(all(self.states[p] in FINAL for p in f.steps) for f in self.files)
        rows = [self._row(f, now) for f in self.files]
        states = [r["state"] for r in rows]
        # The row the drawer keeps in view: the running file, else the first that failed.
        active = next((i for key in ("running", "failed") for i, s in enumerate(states) if s == key), -1)
        count = tr("jobs.count", done=done, total=total)
        left = self._left(now) if self.running else ""
        return {
            "title": tr("jobs.apply_title", batch=self.name),
            "started": tr("jobs.started", time=self.started.strftime("%H:%M")),
            "running": self.running,
            "fraction": self.done_steps() / len(self.states) if self.states else 1.0,
            "count": count,
            "line": f"{count} {tr('status.separator')} {left}" if left else count,
            "summary": self._summary() if not self.running else "",
            "rows": rows,
            "active": active,
        }

    def _left(self, now: float) -> str:
        ended = [f for f in self.files if f.started is not None and f.ended is not None]
        if not ended:
            return ""
        each = sum(f.ended - f.started for f in ended) / len(ended)  # type: ignore[operator]
        waiting = sum(not all(self.states[p] in FINAL for p in f.steps) for f in self.files)
        seconds = each * waiting
        return tr_plural("jobs.left", math.ceil(seconds / 60)) if seconds >= 60 else tr("jobs.left_soon")

    def _summary(self) -> str:
        if self.failed:
            return tr("jobs.summary.failed", error=self.failed)
        states = [self._file_state(f) for f in self.files]
        text = tr(
            "jobs.summary.done",
            done=states.count("done"),
            failed=states.count("failed"),
            other=sum(s not in ("done", "failed") for s in states),
        )
        return tr("jobs.summary.cancelled", summary=text) if self.result and self.result.cancelled else text

    def _file_state(self, file: FileRun) -> str:
        states = [self.states[p] for p in file.steps]
        if StepState.FAILED in states:
            return "failed"
        if StepState.STALE in states:
            return "stale"
        if StepState.RUNNING in states:
            return "running" if self.running else "stopped"
        if all(s is StepState.DONE for s in states):
            return "done"
        if StepState.SKIPPED in states:
            return "skipped"
        return "waiting" if self.running else "stopped"

    def _row(self, file: FileRun, now: float) -> dict[str, Any]:
        state = self._file_state(file)
        phases = [phase for p in file.steps for phase in self._phases(p)]
        if state == "running" and file.started is not None:
            time_text = tr("jobs.so_far", time=clock(now - file.started))
        elif file.started is not None and file.ended is not None:
            time_text = clock(file.ended - file.started)
        else:
            time_text = tr(f"jobs.state.{state}")
        return {
            "path": str(file.path),
            "number": file.number,
            "title": file.title,
            "state": state,
            "phases": phases,
            "time": time_text,
            "result": self._result_lines(file, state),
        }

    def _phases(self, position: int) -> list[dict[str, Any]]:
        step = self.job.steps[position]
        names = PHASES.get(step.plan.stage, ("edit",))
        state = self.states[position]
        record = self.records.get(position)
        detail = record.detail if record is not None else None
        if state is StepState.DONE:
            marks = ["done"] * len(names)
        elif state is StepState.RUNNING:
            fraction = self.fractions.get(position, 0.0)
            # A remux reports its progress while it writes; once written, it is checked, and the original moves only
            # after that, which takes a moment.
            at = 1 if len(names) > 1 and fraction >= 1.0 else 0
            marks = ["done"] * at + ["active" if self.running else "stopped"] + ["waiting"] * (len(names) - at - 1)
        elif state is StepState.FAILED:
            failed = _FAILED_PHASE.get(detail.failure, names[0]) if isinstance(detail, MuxResult) else names[0]
            at = names.index(failed) if failed in names else 0
            marks = ["done"] * at + ["failed"] + ["waiting"] * (len(names) - at - 1)
        elif state in (StepState.STALE, StepState.SKIPPED):
            marks = ["skipped"] * len(names)
        else:
            marks = ["waiting"] * len(names)
        percent = round(self.fractions.get(position, 0.0) * 100)
        return [
            {
                "label": tr(f"jobs.phase.{name}"),
                "state": mark,
                "percent": percent if mark == "active" and name == "write" else -1,
            }
            for name, mark in zip(names, marks, strict=True)
        ]

    def _result_lines(self, file: FileRun, state: str) -> list[str]:
        if state in ("waiting", "running") or (state == "done" and self.running):
            return []  # a finished file says what was checked once the job ends; failures say why at once
        if state == "stopped":
            return [tr("jobs.result.stopped")]
        lines: list[str] = []
        for position in file.steps:
            record = self.records.get(position)
            step = self.job.steps[position]
            if record is None:
                continue
            if record.state is StepState.STALE:
                lines.append(tr("jobs.result.stale"))
            elif record.state is StepState.SKIPPED:
                lines.append(tr("jobs.result.skipped"))
            elif isinstance(record.detail, MuxResult):
                plan = step.plan.plan if isinstance(step.plan.plan, MuxPlan) else None
                lines += mux_text(plan, record.detail)
            elif isinstance(record.detail, ApplyResult) and record.detail.ok:
                lines.append(tr("jobs.result.edited"))
            elif record.state is StepState.DONE:
                lines.append(tr("jobs.result.done"))
            else:
                lines.append(tr("jobs.result.failed", message=record.message or tr("jobs.check.none")))
        return lines


type Pipeline = Callable[[], tuple[Sequence[Stage], Read]]


class Jobs(QObject):
    """The job of this window, new or resumed, and the offer of jobs an earlier run left unfinished. `ended` carries
    the `JobResult` once a job stops (or None when it failed as a whole), for the window to read the written files
    again and unlock the batch."""

    changed = Signal()
    offer_changed = Signal()
    started = Signal()
    ended = Signal(object)

    def __init__(
        self,
        store: JobStore,
        pipeline: Pipeline,
        names: Callable[[Path], tuple[str, str]],
        *,
        now: Callable[[], float] = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._pipeline = pipeline
        self._names = names
        self._now = now
        self._runner: JobRunner | None = None
        self._progress: JobProgress | None = None
        self._offers: list[tuple[JobSummary, bool]] = []  # (job, can be resumed)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.changed)

    # Running

    @property
    def busy(self) -> bool:
        return self._runner is not None

    def paths(self) -> set[Path]:
        """The files of the running job, whose batch is locked while it runs."""
        return {f.path for f in self._progress.files} if self._progress is not None and self.busy else set()

    def start(self, job_id: int, name: str) -> None:
        """Run a stored job, new or interrupted. Raises `UnresumableJobError` for one that cannot be read back."""
        if self._runner is not None:
            raise RuntimeError("a job is already running")
        job = self.store.load(job_id)
        stages, read = self._pipeline()
        self._progress = JobProgress(job, name, datetime.now(), self._names)
        runner = JobRunner(self.store, stages, read, self)
        # Bound methods: the runner emits from the pool thread, and Qt queues each signal to this object's thread.
        runner.step_changed.connect(self._on_step)
        runner.step_progress.connect(self._on_fraction)
        runner.finished.connect(self._on_finished)
        runner.failed.connect(self._on_failed)
        self._runner = runner
        runner.start(job_id)
        self._timer.start()
        self.started.emit()
        self.changed.emit()

    @Slot()
    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()

    def _on_step(self, record: StepRecord) -> None:
        if self._progress is not None:
            self._progress.step_changed(record, self._now())
            self.changed.emit()

    def _on_fraction(self, path: Path, stage: str, fraction: float) -> None:
        if self._progress is not None:
            self._progress.step_progress(path, stage, fraction)
            self.changed.emit()

    def _on_finished(self, result: JobResult) -> None:
        if self._progress is not None:
            self._progress.finish(result, self._now())
        self._end(result)

    def _on_failed(self, error: Exception) -> None:
        _log.error("A job failed: %s", error)
        if self._progress is not None:
            self._progress.failed = str(error) or type(error).__name__
        self._end(None)

    def _end(self, result: JobResult | None) -> None:
        if self._runner is not None:
            self._runner.deleteLater()
        self._runner = None
        self._timer.stop()
        self.changed.emit()
        self.ended.emit(result)

    @Slot()
    def clear(self) -> None:
        """Take a finished job off the drawer."""
        if self._runner is None:
            self._progress = None
            self.changed.emit()

    @Property(bool, notify=changed)
    def running(self) -> bool:
        return self._runner is not None

    @Property("QVariantMap", notify=changed)
    def view(self) -> dict[str, Any]:
        return self._progress.view(self._now()) if self._progress is not None else {}

    @Property(str, notify=changed)
    def status(self) -> str:
        """The status bar's "Applying Season 1 · 4 of 10"."""
        if self._progress is None or self._runner is None:
            return ""
        view = self._progress.view(self._now())
        return tr("jobs.status", title=self._progress.name, count=view["count"])

    # Unfinished jobs from an earlier run

    def check_unfinished(self) -> None:
        """Gather the jobs an earlier run left unfinished, to offer one at a time; never resumed without a yes."""
        offers = []
        for job in self.store.unfinished():
            try:
                self.store.load(job.id)
            except UnresumableJobError:
                offers.append((job, False))
                continue
            offers.append((job, True))
        self._offers = offers
        self.offer_changed.emit()

    @Property("QVariantMap", notify=offer_changed)
    def offer(self) -> dict[str, Any]:
        if not self._offers:
            return {}
        job, resumable = self._offers[0]
        key = "jobs.unfinished" if resumable else "jobs.unresumable"
        return {
            "id": job.id,
            "resumable": resumable,
            "text": tr(key, done=job.finished, total=job.steps, profile=job.profile_name),
            "when": datetime.fromtimestamp(job.created).strftime("%Y-%m-%d %H:%M"),
        }

    def _next_offer(self) -> tuple[JobSummary, bool] | None:
        if not self._offers:
            return None
        offer = self._offers.pop(0)
        self.offer_changed.emit()
        return offer

    @Slot()
    def resume_offer(self) -> None:
        if self._runner is not None or not self._offers or not self._offers[0][1]:
            return
        job, _ = self._next_offer()  # type: ignore[misc]
        try:
            self.start(job.id, tr("jobs.resumed_name", profile=job.profile_name))
        except UnresumableJobError:
            _log.exception("The job could not be read back")

    @Slot()
    def discard_offer(self) -> None:
        if (offer := self._next_offer()) is not None:
            self.store.discard(offer[0].id)

    @Slot()
    def later_offer(self) -> None:
        self._next_offer()
