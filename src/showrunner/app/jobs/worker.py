"""Running a job off the UI thread and handing its progress and result back to it through signals."""

from __future__ import annotations

import threading
from collections.abc import Sequence

from PySide6.QtCore import QObject, Signal

from showrunner.app.jobs.run import JobResult, Read, run_job
from showrunner.app.jobs.stages import Stage
from showrunner.app.jobs.store import JobStore
from showrunner.app.library.loader import BackgroundJob


class JobRunner(QObject):
    """One job at a time, started fresh or resumed alike. `progress` counts finished steps; `finished` carries a
    `JobResult`, whose `cancelled` is set when Cancel stopped it."""

    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, store: JobStore, stages: Sequence[Stage], read: Read, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._stages = tuple(stages)
        self._read = read
        self._cancel = threading.Event()
        self._job: BackgroundJob | None = None

    @property
    def busy(self) -> bool:
        return self._job is not None

    def start(self, job_id: int) -> None:
        if self._job is not None:
            raise RuntimeError("a job is already running")
        self._cancel.clear()

        def work() -> JobResult:
            return run_job(
                self._store,
                job_id,
                self._stages,
                read=self._read,
                progress=self.progress.emit,
                cancel=self._cancel,
            )

        job = BackgroundJob(work)
        job.finished.connect(self._on_finished)
        job.failed.connect(self._on_failed)
        self._job = job
        job.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _on_finished(self, result: JobResult) -> None:
        self._job = None
        self.finished.emit(result)

    def _on_failed(self, error: Exception) -> None:
        self._job = None
        self.failed.emit(error)
