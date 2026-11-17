"""Running a library load off the UI thread and handing its results back to it through signals."""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection, Iterable
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal

from showrunner.app.library.library import LibraryLoad
from showrunner.app.library.service import load_library
from showrunner.stages.scan.probing import Reader
from showrunner.tools.probe import Programs, probe


class BackgroundJob(QObject):
    """Runs `work` once on a pool thread. `finished` or `failed` is delivered on the thread this object lives on.

    A signal emitted from the pool thread is queued to receivers that live on the UI thread, so a slot
    never runs on the worker's thread.
    """

    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, work: Callable[[], object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work

    def start(self) -> None:
        QThreadPool.globalInstance().start(self._run)

    def _run(self) -> None:
        try:
            try:
                result = self._work()
            except Exception as error:  # anything the work raises is reported, never lost on the pool thread
                self.failed.emit(error)
            else:
                self.finished.emit(result)
        except RuntimeError:
            # The job was deleted while the work ran, as the application shuts down: nobody is left to tell.
            return


class LibraryLoader(QObject):
    """One library load at a time. `progress` counts the videos whose tracks were read; `finished` carries a
    `LibraryLoad`, which holds what was found so far when the load was cancelled."""

    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(object)

    def __init__(
        self,
        *,
        programs: Programs | None = None,
        read: Reader = probe,
        cache: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._programs = programs
        self._read = read
        self._cache = cache  # the read cache file; None reads every file
        self._cancel = threading.Event()
        self._job: BackgroundJob | None = None

    @property
    def busy(self) -> bool:
        return self._job is not None

    def start(self, paths: Iterable[Path], known: Collection[Path] = ()) -> None:
        if self._job is not None:
            raise RuntimeError("a library load is already running")
        paths = tuple(paths)
        self._cancel.clear()

        def work() -> LibraryLoad:
            return load_library(
                paths,
                known=known,
                programs=self._programs,
                read=self._read,
                progress=lambda done, total, _path: self.progress.emit(done, total),
                cancel=self._cancel,
                cache=self._cache,
            )

        job = BackgroundJob(work)
        job.finished.connect(self._on_finished)
        job.failed.connect(self._on_failed)
        self._job = job
        job.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _on_finished(self, load: LibraryLoad) -> None:
        self._job = None
        self.finished.emit(load)

    def _on_failed(self, error: Exception) -> None:
        self._job = None
        self.failed.emit(error)
