"""Live plans: the selected batch planned again on a pool thread after every choice, so counts and marks follow."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from showrunner.app.jobs.preview import Preview
from showrunner.app.library.loader import BackgroundJob

_log = logging.getLogger(__name__)

type Work = Callable[[], Preview]


class LivePlanner(QObject):
    """One plan at a time. A request while one runs replaces any request still waiting and starts when the running
    plan ends, whose result is then dropped: only the newest choices reach the screen, and an old plan never
    overwrites a newer one. `planned` carries the request's token and the preview."""

    planned = Signal(object, object)
    busy_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._job: BackgroundJob | None = None
        self._token: object = None
        self._waiting: tuple[object, Work] | None = None

    @property
    def busy(self) -> bool:
        return self._job is not None

    def request(self, token: object, work: Work) -> None:
        self._waiting = (token, work)
        if self._job is None:
            self._start()

    def _start(self) -> None:
        assert self._waiting is not None
        self._token, work = self._waiting
        self._waiting = None
        job = BackgroundJob(work, self)
        # Bound methods, not closures: Qt then delivers on this object's thread, never on the pool thread.
        job.finished.connect(self._on_finished)
        job.failed.connect(self._on_failed)
        was_busy, self._job = self.busy, job
        job.start()
        if not was_busy:
            self.busy_changed.emit()

    def _on_finished(self, result: Preview) -> None:
        self._end()
        if self._waiting is not None:
            self._start()
            return
        self.busy_changed.emit()
        self.planned.emit(self._token, result)

    def _on_failed(self, error: Exception) -> None:
        _log.error("A live plan failed: %s", error)
        self._end()
        if self._waiting is not None:
            self._start()
        else:
            self.busy_changed.emit()

    def _end(self) -> None:
        if self._job is not None:
            self._job.deleteLater()
        self._job = None
