"""Preview and Apply for the main window: the job queue run off the UI thread, and whether the preview on screen
still matches the options, the stages and the library."""

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from showrunner.app.dependencies.service import mkvpropedit_from, probe_file, programs_from
from showrunner.app.jobs.preview import FileOutcome, FilePreview, Preview, preview
from showrunner.app.jobs.run import JobResult, create_job
from showrunner.app.jobs.stages import Stage, pipeline
from showrunner.app.jobs.store import JobStore, StepState
from showrunner.app.jobs.worker import JobRunner
from showrunner.app.library.loader import BackgroundJob
from showrunner.core.media import MediaFile, MediaItem
from showrunner.tools.dependencies.detect import DependencyStatus
from showrunner.ui.settings.session import ProfileSession

_log = logging.getLogger(__name__)

Pipeline = Callable[[dict[str, DependencyStatus], str], Sequence[Stage]]


def default_pipeline(statuses: dict[str, DependencyStatus], source: str) -> tuple[Stage, ...]:
    return pipeline(programs_from(statuses), mkvpropedit_from(statuses), source=source)


class StageController(QObject):
    """`changed` fires whenever what the stage bar shows may differ: a preview arrived or went out of date, a job
    started or ended. `progress` counts the steps of a running job; `applied` carries its `JobResult` once the
    written files were read again; `failed` a message for an error that stopped a preview or a job."""

    changed = Signal()
    progress = Signal(int, int)
    applied = Signal(object)
    files_read = Signal(object)  # path -> MediaFile, read again after Apply
    failed = Signal(str)

    def __init__(
        self,
        session: ProfileSession,
        store: JobStore,
        *,
        make_pipeline: Pipeline = default_pipeline,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._store = store
        self._make_pipeline = make_pipeline
        self._statuses: dict[str, DependencyStatus] = {}
        self._source = ""
        self._library_version = 0
        self.preview: Preview | None = None
        self.preview_time: datetime.datetime | None = None
        self._preview_version = -1
        self.left_out: set[Path] = set()  # files the user left out of Apply
        self._job: BackgroundJob | None = None
        self._runner: JobRunner | None = None
        self._done: Callable[[object], None] = lambda _result: None
        session.changed.connect(self.changed)

    # Inputs

    @property
    def store(self) -> JobStore:
        return self._store

    @property
    def statuses(self) -> dict[str, DependencyStatus]:
        return self._statuses

    def set_statuses(self, statuses: dict[str, DependencyStatus]) -> None:
        self._statuses = dict(statuses)
        self.changed.emit()

    def set_source(self, source: str) -> None:
        self._source = source
        self.changed.emit()

    def library_changed(self) -> None:
        """Paired subtitle files are not stamped, so any change of the library makes the preview out of date."""
        self._library_version += 1
        self.changed.emit()

    def stages(self) -> tuple[Stage, ...]:
        return tuple(self._make_pipeline(self._statuses, self._source))

    def stage_ids(self) -> set[str]:
        return {s.id for s in self.stages()}

    def blocked(self) -> set[str]:
        """Blocked stages among those that run."""
        return set(self._session.blocks()) & self.stage_ids()

    # State

    @property
    def busy(self) -> bool:
        return self._job is not None or self._runner is not None

    @property
    def is_current(self) -> bool:
        return (
            self.preview is not None
            and self._preview_version == self._library_version
            and self.preview.is_current(self._session.profile, self.stages(), self.blocked())
        )

    def file(self, path: Path) -> FilePreview | None:
        if self.preview is None:
            return None
        return next((f for f in self.preview.files if f.item.file.path == path), None)

    def to_write(self) -> list[FilePreview]:
        """The files Apply would write."""
        files = self.preview.files if self.preview else ()
        return [f for f in files if f.writes and f.item.file.path not in self.left_out]

    def marks(self) -> dict[Path, str]:
        """Tree dots from the preview: a refused or stuck file needs a decision, a changed one is planned."""
        dots = {}
        for f in self.preview.files if self.preview else ():
            if f.outcome in (FileOutcome.REFUSED, FileOutcome.NEEDS_REMUX, FileOutcome.UNWRITTEN):
                dots[f.item.file.path] = "accent_ink"
            elif f.outcome is FileOutcome.CHANGES:
                dots[f.item.file.path] = "control"
        return dots

    # Preview

    def start_preview(self, items: Sequence[MediaItem]) -> None:
        if self.busy:
            return
        profile, stages, blocked = self._session.profile, self.stages(), self.blocked()
        version = self._library_version
        items = tuple(items)

        def work() -> Preview:
            return preview(items, profile, stages, blocked=blocked, finished=self._store.is_finished)

        def done(result: Preview) -> None:
            self._job = None
            self.preview = result
            self.preview_time = datetime.datetime.now()
            self._preview_version = version
            self.changed.emit()

        self._run(work, done)

    def _run(self, work: Callable[[], object], done: Callable[[object], None]) -> None:
        job = BackgroundJob(work, self)
        # Bound methods, not the closure: Qt then delivers on this object's thread, never on the pool thread.
        self._done = done
        job.finished.connect(self._on_done)
        job.failed.connect(self._on_failed)
        self._job = job
        self.changed.emit()
        job.start()

    def _on_done(self, result: object) -> None:
        self._done(result)

    def _on_failed(self, error: Exception) -> None:
        self._job = None
        self._runner = None
        _log.error("A preview or job failed: %s", error)
        self.failed.emit(str(error) or type(error).__name__)
        self.changed.emit()

    # Apply and resume

    def apply(self) -> None:
        """Store the current preview as a job and run it. Raises `StalePreviewError` for an out-of-date one."""
        if self.busy or self.preview is None or not self.is_current:
            return
        files = tuple(f for f in self.preview.files if f.item.file.path not in self.left_out)
        kept = replace(self.preview, files=files)
        job_id = create_job(self._store, kept, self._session.profile, self.stages(), blocked=self.blocked())
        self.run(job_id)

    def run(self, job_id: int) -> None:
        """Run a stored job, new or interrupted."""
        programs = programs_from(self._statuses)
        runner = JobRunner(self._store, self.stages(), lambda path: probe_file(path, programs), self)
        runner.progress.connect(self.progress)
        runner.finished.connect(self._on_job_finished)
        runner.failed.connect(self._on_failed)
        self._runner = runner
        self.changed.emit()
        runner.start(job_id)

    def leave_out(self, path: Path, out: bool) -> None:
        if out:
            self.left_out.add(path)
        else:
            self.left_out.discard(path)
        self.changed.emit()

    def cancel(self) -> None:
        if self._runner is not None:
            self._runner.cancel()

    def _on_job_finished(self, result: JobResult) -> None:
        self._runner = None
        self.preview = None
        written = sorted({s.path for s in result.steps if s.state is StepState.DONE})
        programs = programs_from(self._statuses)

        def work() -> dict[Path, MediaFile]:
            files = {}
            for path in written:
                try:
                    files[path] = probe_file(path, programs)
                except Exception:  # a file that cannot be read again keeps its old tracks until the next load
                    _log.exception("Could not read %s again", path)
            return files

        def done(files: dict[Path, MediaFile]) -> None:
            self._job = None
            self.files_read.emit(files)
            self.applied.emit(result)
            self.changed.emit()

        self._run(work, done)
