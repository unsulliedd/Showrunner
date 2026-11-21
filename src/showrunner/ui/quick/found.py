"""The programs the window works with, as found on this machine, and the list of languages MKVToolNix knows.

Both are read on pool threads. Which stages plan depends on the programs found, so the open place plans again when
they are known; unfinished jobs are offered once, at the first check, since resuming one runs them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from showrunner.app.dependencies.service import check, programs_from
from showrunner.app.languages import read_languages, use_languages
from showrunner.app.library.loader import BackgroundJob
from showrunner.tools.dependencies.detect import State
from showrunner.tools.dependencies.specs import SPEC_BY_ID
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.quick.jobs import Jobs
from showrunner.ui.quick.workspace import Statuses, Workspace

_log = logging.getLogger(__name__)

# The programs the first-run screen and the status bar show: the ones that read and write the files today.
SHOWN_PROGRAMS: tuple[str, ...] = ("mkvtoolnix", "ffmpeg")


def check_shown() -> Statuses:
    return {spec_id: check(SPEC_BY_ID[spec_id]) for spec_id in SHOWN_PROGRAMS}


class FoundPrograms(QObject):
    programs_changed = Signal()
    languages_read = Signal()  # MKVToolNix's list of languages arrived, or its absence is known

    def __init__(
        self,
        workspace: Workspace,
        jobs: Jobs,
        statuses: Callable[[], Statuses] = check_shown,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._jobs = jobs
        self._check = statuses
        self._offered = False  # unfinished jobs are offered once, when the programs are first known
        self.known_codes: frozenset[str] | None = None  # the codes MKVToolNix accepts; None without it
        self._languages_from: Path | None = None  # the mkvmerge whose list of languages was asked for

    def refresh(self) -> None:
        # Bound slots: a check that ends after the window is gone reaches nothing, as Qt drops a deleted receiver.
        job = BackgroundJob(self._check)
        job.finished.connect(self._on_statuses)
        job.failed.connect(self._on_check_failed)
        job.start()

    def _on_check_failed(self, error: Exception) -> None:
        _log.error("Checking the programs failed: %s", error)
        self._set_statuses({})

    def _on_statuses(self, statuses: Statuses) -> None:
        self._set_statuses(statuses)

    def _set_statuses(self, statuses: Statuses) -> None:
        self._workspace.statuses = statuses
        self._load_languages(programs_from(statuses).mkvmerge)
        self.programs_changed.emit()
        self._workspace.replan()  # which stages plan depends on the programs found
        if not self._offered:
            # Jobs are offered once the programs are known, since resuming one runs them.
            self._offered = True
            self._jobs.check_unfinished()

    def _load_languages(self, mkvmerge: Path | None) -> None:
        """Read MKVToolNix's list of languages once per program: the picker works without it, and with it gains the
        codes babelfish lacks and the check of a typed tag. Asked in the background, taken here, where languages are
        read."""
        if self._languages_from == mkvmerge and (mkvmerge is None or self.known_codes is not None):
            return
        self._languages_from = mkvmerge
        job = BackgroundJob(partial(read_languages, mkvmerge))
        job.finished.connect(self._on_languages_read)
        job.failed.connect(self._on_languages_read)
        job.start()

    def _on_languages_read(self, rows: object) -> None:
        self.known_codes = use_languages(rows) if isinstance(rows, tuple) else use_languages(None)
        self.languages_read.emit()
        self._workspace.replan()  # a saved choice of a code that only MKVToolNix lists can now be read

    @property
    def programs(self) -> list[dict[str, Any]]:
        statuses = self._workspace.statuses
        rows = []
        for spec_id in SHOWN_PROGRAMS:
            name = tr(SPEC_BY_ID[spec_id].name_key)
            status = statuses.get(spec_id) if statuses is not None else None
            state = "checking" if statuses is None else (status.state.value if status else State.MISSING.value)
            version = (status.version or "") if status is not None else ""
            rows.append(
                {
                    "id": spec_id,
                    "name": name,
                    "about": tr(f"program.about.{spec_id}"),
                    "state": state,
                    "found": state == State.FOUND.value,
                    "version": version,
                    "status": tr(f"program.state.{state}", name=name, version=version),
                }
            )
        return rows
