"""The programs the window works with, as found on this machine, the AI server's state, and the list of languages
MKVToolNix knows.

All are read on pool threads. Which stages plan depends on the programs found and on the AI server, so the open place
plans again when they are known or change; unfinished jobs are offered once, at the first check, since resuming one
runs them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from showrunner.app.ai import AI, AiStatus
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
# Checked as well, since plans depend on them, though only Settings shows them.
_PLANNED_PROGRAMS: tuple[str, ...] = (*SHOWN_PROGRAMS, "tesseract")


def check_shown() -> Statuses:
    return {spec_id: check(SPEC_BY_ID[spec_id]) for spec_id in _PLANNED_PROGRAMS}


class FoundPrograms(QObject):
    programs_changed = Signal()
    languages_read = Signal()  # MKVToolNix's list of languages arrived, or its absence is known
    ai_changed = Signal()  # the AI server started or stopped answering, or its models changed

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
        self._asking_ai = False
        self._ai_before: AiStatus | None = None  # the answer the plans had when the server was last asked
        # Each new plan asks the AI server again once its last answer is old, so the plans follow it within moments.
        workspace.rebuilt.connect(self.check_ai)

    def check_ai(self, now: bool = False) -> None:
        """Ask the AI server in the background when its last answer is old, or `now`. Plans read the last answer
        meanwhile; a different answer plans the place again."""
        if self._asking_ai or not (now or AI.stale()):
            return
        self._asking_ai = True
        self._ai_before = AI.status()
        # Bound slots, as for the programs.
        job = BackgroundJob(AI.check)
        job.finished.connect(self._on_ai)
        job.failed.connect(self._on_ai_failed)
        job.start()

    def _on_ai(self, status: AiStatus) -> None:
        self._asking_ai = False
        if status != self._ai_before:
            if not status.running:
                _log.info("The AI server does not answer: %s", status.detail)
            self.ai_changed.emit()
            self._workspace.replan()

    def _on_ai_failed(self, error: Exception) -> None:
        self._asking_ai = False
        _log.error("Asking the AI server failed: %s", error)

    def refresh(self) -> None:
        self.check_ai(now=True)
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
