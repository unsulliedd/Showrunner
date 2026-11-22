"""Review's run and Apply: what goes into the run, starting it, the queue hand-off, and reading written files again.

Apply never runs from a live plan: it plans the batch again with stamps on a pool thread, refuses to start when a
file changed since it was read, stores the job and hands it to `Jobs`, which runs it on a pool thread too. The batch is
locked from the press until the job ends and its files were read again.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject

from showrunner.app.batches.batch import BatchKey, BatchKind
from showrunner.app.dependencies.service import probe_file, programs_from
from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import Preview, preview_each
from showrunner.app.jobs.run import JobResult, Read, StalePreviewError, create_job
from showrunner.app.jobs.stages import Stage
from showrunner.app.jobs.store import JobStore, StepState
from showrunner.app.library.loader import BackgroundJob
from showrunner.app.library.service import read_again, read_subtitles
from showrunner.app.profiles.profile import Profile
from showrunner.app.storage.paths import read_cache_path
from showrunner.core.media import MediaFile, SubtitleFile
from showrunner.stages.mux import MuxResult, Original
from showrunner.tools.probe import probe
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.quick.facts import heading
from showrunner.ui.quick.jobs import Jobs
from showrunner.ui.quick.queue import Queue
from showrunner.ui.quick.review import FILTERS, review
from showrunner.ui.quick.tracks import item_number, item_title
from showrunner.ui.quick.workspace import Workspace

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Applying:
    """What an Apply was pressed with, kept while its stamped preview is made."""

    paths: frozenset[Path]
    profiles: dict[Path, Profile]  # each file's options
    stages: tuple[Stage, ...]
    out: frozenset[Path]
    key: BatchKey  # the place that was applied
    # Each file's plans in the run plan on screen; None for a place added to the queue, which may be queued from the
    # library's menu before its plan arrived and keeps the plans made now.
    live: dict[Path, Any] | None
    name: str  # the batch, as the job names it


class Run(QObject):
    """Review's choices for this run, Apply and Add to queue, the job and the queue, and the lock they hold."""

    def __init__(
        self, workspace: Workspace, store: JobStore, read: Read | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self.read_file = read
        self._applying: _Applying | None = None  # an Apply whose stamped preview is being made
        self._reading: set[Path] = set()  # files a job wrote, being read again: they are as they were until then
        self._apply_message = ""
        self.jobs = Jobs(store, self._job_pipeline, self._names_of, parent=self)
        self.jobs.started.connect(self._on_lock_changed)
        self.jobs.ended.connect(self._on_job_ended)
        self.queue = Queue(self.jobs, parent=self)

    # Review: what goes into the run

    @property
    def review(self) -> dict[str, Any]:
        given = self._workspace.shown.get("review_input")
        return self._workspace.part("review", lambda: review(given)) if given is not None else {}

    @property
    def review_filter(self) -> str:
        return self._workspace.review_filter

    @review_filter.setter
    def review_filter(self, key: str) -> None:
        if key in FILTERS and key != self._workspace.review_filter:
            self._workspace.review_filter = key
            self._workspace.refresh()

    def set_in_run(self, group: str, on: bool) -> None:
        """A group's "In this run" for the open place and what lies inside it: left out, it is planned as if its
        options asked for nothing; they stay. A place inside that set its own value keeps it."""
        workspace = self._workspace
        if workspace.key is None or workspace.locked or group not in set(ChangeGroup):
            return
        workspace.left_out.set_group(workspace.key, ChangeGroup(group), not on)
        workspace.replan()

    def set_file_in_run(self, path: str, on: bool) -> None:
        """A file's tick box in Review, a value of its own place: left out of this run only, nothing saved; its choices
        and exclusion stay."""
        workspace = self._workspace
        item = workspace.file_item(path)
        if workspace.key is None or workspace.locked or item is None:
            return
        workspace.left_out.set_file(BatchKey.file(item).in_show(workspace.key), not on)
        workspace.refresh()

    def set_original(self, original: str) -> None:
        """Where the originals of remuxed files go: the Recycle Bin or the keep folder beside them."""
        workspace = self._workspace
        if workspace.key is None or workspace.locked or original not in set(Original):
            return
        mux = workspace.batches.profile(workspace.key).for_stage("mux")
        if mux.original != original:
            workspace.set_options("mux", replace(mux, original=Original(original)))

    # Apply

    def locked_paths(self) -> set[Path]:
        return (set(self._applying.paths) if self._applying is not None else set()) | self.jobs.paths() | self._reading

    @property
    def applying(self) -> bool:
        return self._applying is not None or self.jobs.busy

    @property
    def can_apply(self) -> bool:
        """Only a plan that is on screen and current can be applied, one job at a time."""
        workspace = self._workspace
        return (
            workspace.key is not None
            and not self.applying
            and not workspace.locked
            and not workspace.planning
            and workspace.statuses is not None
            and bool(workspace.current_files(workspace.run_preview))
            and workspace.change_count > 0
        )

    @property
    def apply_message(self) -> str:
        """Why the last Apply did not start, worded; empty after one that did."""
        return self._apply_message

    def _set_apply_message(self, text: str) -> None:
        self._apply_message = text
        self._workspace.apply_changed.emit()

    def apply(self) -> None:
        """Plan the batch again with stamps on a pool thread; `_on_stamped` decides whether it may run."""
        if not self.can_apply or self._workspace.key is None or self._workspace.run_preview is None:
            return
        self._apply_message = ""
        self._stamp({f.item.file.path: f.plans for f in self._workspace.run_preview.files})

    @property
    def can_queue(self) -> bool:
        """The selected place can be added to the queue: the programs are known, no Apply or add is getting ready,
        and its files are not being written. Its plan need not have arrived: the add plans it again anyway."""
        workspace = self._workspace
        return (
            workspace.key is not None
            and workspace.statuses is not None
            and self._applying is None
            and not workspace.locked
        )

    def add_to_queue(self) -> None:
        """Queue the selected place with each file's options as they are now, the groups and files this run leaves
        out included; `_on_stamped` stores its job and hands it to the queue."""
        if self.can_queue:
            self._stamp(None)

    def _stamp(self, live: dict[Path, Any] | None) -> None:
        """Plan the selected place with stamps on a pool thread, for Apply (`live`, the plans on screen) or for the
        queue (None)."""
        workspace = self._workspace
        key = workspace.key
        assert key is not None
        stages = tuple(workspace.make_pipeline(workspace.statuses or {}))
        items = tuple(workspace.items)
        # The groups this run leaves out of a file are emptied in its own options, which the job stores.
        profiles = workspace.run_profiles(items, workspace.batches.file_profiles(items, key))
        head = heading(key, items)
        self._applying = _Applying(
            paths=frozenset(i.file.path for i in items),
            profiles=profiles,
            stages=stages,
            out=workspace.files_out() | {i.file.path for i in items if i.file.path in workspace.excluded_files},
            key=key,
            live=live,
            name=tr("common.list_separator").join((head.over, head.title))
            if key.season or key.kind in (BatchKind.EXTRAS, BatchKind.EXTRA)
            else head.title,
        )
        store = self.jobs.store

        def work() -> Preview:
            return preview_each(items, profiles, stages, finished=store.is_finished)

        job = BackgroundJob(work)
        job.finished.connect(self._on_stamped)
        job.failed.connect(self._on_stamp_failed)
        self._on_lock_changed()
        job.start()

    def _on_stamped(self, stamped: Preview) -> None:
        given, self._applying = self._applying, None
        if given is None:
            return
        in_run = [f for f in stamped.files if f.item.file.path not in given.out]
        # The plans were made from the tracks the library read; a file whose size or modification time moved since
        # was written by another program, even when its size stayed.
        changed = [
            f.item.file.path
            for f in in_run
            if f.stamp is None
            or f.item.file.size not in (0, f.stamp.size)
            or f.item.file.modified_ns not in (0, f.stamp.mtime_ns)
        ]
        message = ""
        refused = "queue.refused" if given.live is None else "review.refused"
        if changed:
            message = tr_plural(f"{refused}.changed", len(changed))
            self._read_again({path: path for path in changed})
        elif given.live is not None and any(f.plans != given.live.get(f.item.file.path) for f in in_run):
            message = tr("review.refused.plans")
        elif not any(f.writes for f in in_run):
            message = tr(f"{refused}.nothing")
        elif given.live is None:
            paths = [f.item.file.path for f in in_run if f.stamp is not None and f.writes]
            # Both paths store the job alike: what goes wrong is said, and the lock below is always given back.
            try:
                self.queue.add(
                    given.name,
                    paths,
                    lambda: create_job(
                        self.jobs.store, stamped, given.profiles, given.stages, left_out_files=given.out
                    ),
                )
            except StalePreviewError:
                message = tr("queue.refused.plans")
            except (OSError, sqlite3.Error) as error:
                _log.exception("Could not store the queued job")
                message = tr("queue.refused.error", error=error)
        else:
            try:
                job_id = create_job(
                    self.jobs.store,
                    stamped,
                    given.profiles,
                    given.stages,
                    left_out_files=given.out,
                )
            except StalePreviewError:
                message = tr("review.refused.plans")
            except (OSError, sqlite3.Error) as error:
                _log.exception("Could not store the job")
                message = tr("review.refused.error", error=error)
            else:
                self.jobs.start(job_id, given.name)
                # The run took what was unticked; the next one starts with every box ticked.
                self._workspace.left_out.clear(given.key)
                self._workspace.replan()
        if given.live is None:
            if message:
                self.queue.refuse(message)
        else:
            self._set_apply_message(message)
        self._on_lock_changed()

    def _on_stamp_failed(self, error: Exception) -> None:
        _log.error("The preview for Apply failed: %s", error)
        given, self._applying = self._applying, None
        message = tr(
            "queue.refused.error" if given is not None and given.live is None else "review.refused.error",
            error=str(error) or type(error).__name__,
        )
        if given is not None and given.live is None:
            self.queue.refuse(message)
        else:
            self._set_apply_message(message)
        self._on_lock_changed()

    def _on_lock_changed(self) -> None:
        self._workspace.batch_changed.emit()
        self._workspace.apply_changed.emit()
        self._workspace.loading_changed.emit()  # whether the library can be closed

    # The job

    def _job_pipeline(self) -> tuple[Sequence[Stage], Read]:
        """The stages and the reader a job runs with: those of the programs found now."""
        return tuple(self._workspace.make_pipeline(self._workspace.statuses or {})), self._reader()

    def _reader(self) -> Read:
        """A reader that holds what it needs: it runs on a pool thread, which must never reach this object."""
        if self.read_file is not None:
            return self.read_file
        return partial(probe_file, programs=programs_from(self._workspace.statuses or {}))

    def _names_of(self, path: Path) -> tuple[str, str]:
        """A job row's number and title, from the library when the file is in it."""
        item = self._workspace.model.library.item(path)
        return (item_number(item), item_title(item)) if item is not None else ("", path.name)

    def _on_job_ended(self, result: JobResult | None) -> None:
        """Read the written files again, so the window shows them as they are now, and unlock the batch."""
        written: dict[Path, Path] = {}
        gone: list[Path] = []
        if result is None:  # the job failed as a whole: any of its files may have been written
            written = {path: path for path in self.jobs.files()}
        else:
            for record in result.steps:
                # A step that stopped (failed, or cancelled while it ran) may have written before it did.
                if record.state in (StepState.DONE, StepState.FAILED, StepState.RUNNING):
                    written[record.path] = record.written or written.get(record.path, record.path)
                if isinstance(record.detail, MuxResult):
                    gone += record.detail.taken
        self._read_again(written, gone, self.jobs.beside_files())
        self._on_lock_changed()

    # Reading files again

    def _read_again(
        self, paths: dict[Path, Path], gone: Sequence[Path] = (), beside: Mapping[Path, Sequence[Path]] | None = None
    ) -> None:
        """Read files again on a pool thread through the read cache, keyed by the path the library knows them by; a
        file that cannot be read keeps what was read before until the next load. The files stay locked until then.
        `beside` are the subtitle files written beside each video, read so the library pairs them with it."""
        known = {i.file.path for i in self._workspace.model.library.items}
        targets = {old: new for old, new in paths.items() if old in known}
        subtitles = {video: written for video, written in (beside or {}).items() if video in known}
        if not targets and not gone and not subtitles:
            return
        programs = programs_from(self._workspace.statuses or {})
        injected, cache = self.read_file, read_cache_path()
        reader = probe if injected is None else lambda path, _programs, *, cancel: injected(path)

        def work() -> tuple[
            dict[Path, MediaFile], tuple[Path, ...], frozenset[Path], dict[Path, tuple[SubtitleFile, ...]]
        ]:
            files = read_again(targets, programs, read=reader, cache=cache)
            return files, tuple(gone), frozenset(targets), read_subtitles(subtitles)

        self._reading |= targets.keys()
        job = BackgroundJob(work)
        job.finished.connect(self._on_read_again)
        job.failed.connect(self._on_read_again_failed)
        job.start()

    def _on_read_again(
        self,
        result: tuple[dict[Path, MediaFile], tuple[Path, ...], frozenset[Path], dict[Path, tuple[SubtitleFile, ...]]],
    ) -> None:
        files, gone, targets, subtitles = result
        self._reading -= targets
        self._workspace.model.replace_files(files, gone, subtitles)
        # The batch is selected again, so it holds the files as read now; a file with a new name opens its season.
        self._workspace.reselect()
        self._on_lock_changed()

    def _on_read_again_failed(self, error: Exception) -> None:
        _log.error("Reading files again failed: %s", error)
        self._reading.clear()
        self._on_lock_changed()
