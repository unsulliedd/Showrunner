"""The drawer's Queue tab: places added from the library's menu, each a stored job made when it was added, run one
after another through `Jobs`, which runs Apply's jobs too, so a queue item is written, checked and its original kept
or recycled exactly as Apply does it. The queue lives in the job store and comes back after a restart, paused."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from showrunner.app.jobs.queue import ItemState, can_retry, item_state, next_item, place
from showrunner.app.jobs.run import JobResult
from showrunner.app.jobs.store import FINAL, QueuedJob, QueueMark, StepState, UnresumableJobError
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.jobs import Jobs, reason_text


class Queue(QObject):
    """`noted` is emitted when an add was queued or refused, for the window to show the queue and its note."""

    changed = Signal()
    noted = Signal()

    def __init__(self, jobs: Jobs, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._store = jobs.store
        self._items = self._store.queued()
        self._running: int | None = None  # the item whose job `Jobs` runs now
        self._going = False  # Start was pressed and neither Pause nor the end of the queue came since
        self._closing = False  # the window closes: a cancelled job is interrupted, not cancelled by the user
        self._note = ""
        jobs.ended.connect(self._on_ended)
        jobs.changed.connect(self.changed)

    def _reload(self) -> None:
        self._items = self._store.queued()
        self.changed.emit()

    def _set_note(self, text: str) -> None:
        self._note = text
        self.changed.emit()

    # Adding

    def add(self, name: str, paths: Sequence[Path], create: Callable[[], int]) -> None:
        """Queue a place whose job `create` stores, unless a file of it is held by an unfinished item (`place`); a
        waiting item it holds every file of is replaced. Says what happened in the note."""
        placement = place(self._items, paths, self._running)
        if placement.clash is not None:
            self.refuse(tr("queue.note.clash", place=name, item=placement.clash.name))
            return
        job_id = create()
        for old in placement.replaces:
            self._store.discard(old.id)
        self._store.enqueue(job_id, name, paths)
        files = tr_plural("queue.files", len(paths))
        key = "queue.note.replaced" if placement.replaces else "queue.note.added"
        self._note = tr(key, place=name, files=files)
        self._reload()
        self.noted.emit()
        self._next()

    def refuse(self, text: str) -> None:
        """Say why a place was not queued."""
        self._set_note(text)
        self.noted.emit()

    # Running

    def _next(self) -> None:
        """Start the oldest item that can run, while the queue is going and no job runs; stop at the end."""
        if not self._going or self._running is not None or self._jobs.busy:
            return
        while (item := next_item(self._items)) is not None:
            self._running = item.id
            try:
                self._jobs.start(item.id, item.name, queued=True)
            except UnresumableJobError as error:
                self._running = None
                self._store.set_mark(item.id, QueueMark.UNREADABLE, str(error))
                self._items = self._store.queued()
                continue
            break
        else:
            self._going = False
        self.changed.emit()

    def _on_ended(self, result: JobResult | None) -> None:
        if self._running is not None:
            if result is None:
                self._store.set_mark(self._running, QueueMark.FAILED, self._jobs.failure)
            elif result.cancelled and not self._closing:
                # Cancel from this tab, the Jobs tab or the top bar alike: the item does not start again by itself.
                self._store.set_mark(self._running, QueueMark.CANCELLED)
            self._running = None
            self._items = self._store.queued()
        self._next()  # also after an Apply's job, which the queue waited for
        self.changed.emit()

    def stop(self) -> None:
        """The window closes: start nothing more. The running item stops with its job and is interrupted, not
        cancelled, so the next start lists it to go on with."""
        self._going = False
        self._closing = True

    @Slot()
    def start(self) -> None:
        self._going = True
        self._next()
        self.changed.emit()

    @Slot()
    def pause(self) -> None:
        """Start no further item; the running one stops once its running step has ended."""
        self._going = False
        if self._running is not None:
            self._jobs.pause()
        self.changed.emit()

    @Slot(int)
    def cancel(self, job_id: int) -> None:
        """Stop the running item at once; a file being written keeps its original."""
        if job_id == self._running:
            self._jobs.cancel()

    @Slot(int)
    def remove(self, job_id: int) -> None:
        if job_id != self._running:
            self._store.discard(job_id)
            self._reload()

    @Slot()
    def clear(self) -> None:
        """Remove every item but the running one: finished, failed and waiting items alike."""
        for item in self._items:
            if item.id != self._running:
                self._store.discard(item.id)
        self._reload()

    @Slot(int)
    def retry(self, job_id: int) -> None:
        """Make a failed or cancelled item wait again and start the queue, as Start does."""
        item = next((i for i in self._items if i.id == job_id), None)
        if item is not None and can_retry(item, item_state(item, item.id == self._running)):
            self._store.retry(job_id)
            self._items = self._store.queued()
            self.start()

    # What QML draws

    @Property(bool, notify=changed)
    def going(self) -> bool:
        return self._going

    @Property(bool, notify=changed)
    def can_start(self) -> bool:
        return not self._going and next_item(self._items) is not None

    @Property(bool, notify=changed)
    def can_clear(self) -> bool:
        return any(item.id != self._running for item in self._items)

    @Property(str, notify=changed)
    def note(self) -> str:
        return self._note

    @Property(str, notify=changed)
    def status(self) -> str:
        """The queue's line over its items: how many wait, and whether it runs."""
        waiting = sum(
            item_state(i, i.id == self._running) in (ItemState.WAITING, ItemState.INTERRUPTED) for i in self._items
        )
        count = tr_plural("queue.waiting", waiting)
        if self._running is not None:
            return tr("queue.status.running" if self._going else "queue.status.pausing", count=count)
        return count

    @Property(int, notify=changed)
    def active(self) -> int:
        """The row the tab keeps in view: the running item; -1 when none runs."""
        return next((n for n, item in enumerate(self._items) if item.id == self._running), -1)

    @Property(list, notify=changed)
    def rows(self) -> list[dict[str, Any]]:
        return [self._row(item) for item in self._items]

    def _row(self, item: QueuedJob) -> dict[str, Any]:
        running = item.id == self._running
        state = item_state(item, running)
        files = tr_plural("queue.files", len(item.paths))
        view = self._jobs.view if running else {}
        done = sum(s in FINAL for s in item.states)
        if state is ItemState.RUNNING:
            detail = view.get("line", "")
        elif state is ItemState.INTERRUPTED:
            detail = tr("queue.detail.interrupted", done=done, total=len(item.states))
        elif state is ItemState.FAILED:
            detail = tr("queue.detail.failed", reason=reason_text(item.reason or item.message))
        elif state is ItemState.CHANGED:
            # Every step has ended and none failed: the rest changed on disk, or follow a step of their file that did.
            written = sum(s is StepState.DONE for s in item.states)
            detail = tr("queue.detail.changed", done=written, total=len(item.states), left=len(item.states) - written)
        elif state in (ItemState.CANCELLED, ItemState.UNREADABLE):
            detail = tr(f"queue.detail.{state.value}")
        else:
            detail = ""
        return {
            "id": item.id,
            "name": item.name,
            "files": files,
            "state": state.value,
            "state_text": tr(f"queue.state.{state.value}"),
            "detail": detail,
            "fraction": view.get("fraction", 0.0)
            if running
            else 1.0
            if state is ItemState.DONE
            else done / max(len(item.states), 1),
            "can_remove": not running,
            "can_cancel": running,
            "can_retry": can_retry(item, state),
        }
