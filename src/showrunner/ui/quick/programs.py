"""Settings → Programs: every external program with its status, and the ways to locate, download or look it up.

Checks and downloads run on a pool thread; their results come back through a bridge's signals, which Qt delivers on
the GUI thread, so the window keeps painting and Cancel stays live. A download is confirmed first, and an installer
is started only after a second yes; both questions are QML popups over `question`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import Property, QObject, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from showrunner.app.dependencies import service
from showrunner.tools.dependencies.detect import DependencyStatus, State, file_name
from showrunner.tools.dependencies.install import DownloadPlan, InstallCancelledError
from showrunner.tools.dependencies.specs import SPEC_BY_ID, SPECS, Archive, DependencySpec
from showrunner.tools.process import ProcessError
from showrunner.ui.i18n.catalog import tr

_TONE = {State.FOUND: "add", State.OUTDATED: "change", State.BROKEN: "drop", State.MISSING: "drop"}


def _megabytes(size: int) -> str:
    return tr("common.size_mb", value=f"{size / 1_000_000:,.1f}")


def row(spec: DependencySpec, status: DependencyStatus | None, has_user_path: bool) -> dict[str, Any]:
    """What one program's row shows: its state, version and place, what it turns on and its actions."""
    if status is None:
        state, tone = tr("dependencies.state.checking"), "faint"
    elif status.state is State.OUTDATED:
        state, tone = tr("dependencies.state.outdated", version=spec.min_version), _TONE[status.state]
    else:
        state, tone = tr(f"dependencies.state.{status.state.value}"), _TONE[status.state]
    details: list[str] = []
    if status is not None and status.path is not None:
        version = (
            tr("dependencies.version", version=status.version) if status.version else tr("dependencies.no_version")
        )
        if status.location:
            location = tr(f"dependencies.location.{status.location.value}")
            version = tr("dependencies.version_location", version=version, location=location)
        details += [version, str(status.path)]
    if status is not None and status.state is State.BROKEN and status.detail:
        details.append(status.detail.splitlines()[0])
    missing = status is None or status.state is State.MISSING
    return {
        "id": spec.id,
        "name": tr(spec.name_key),
        "state": state,
        "tone": tone,
        "details": details,
        "unlocks": tr(
            "dependencies.unlocks",
            features=tr("common.list_separator").join(tr(f"feature.{feature.value}") for feature in spec.features),
        ),
        "user_path": has_user_path,
        "download": tr("dependencies.download" if missing else "dependencies.update"),
        "variants": [
            {"id": variant.id, "label": tr(f"dependencies.variant.{variant.id}")}
            for variant in spec.source.variants
            if len(spec.source.variants) > 1
        ],
    }


class _Bridge(QObject):
    """Carries a job's results to the GUI thread. It has no parent: the job keeps it alive, so a job that ends after
    the window closed emits into an object that still exists, and Qt drops signals whose receiver is gone."""

    progress = Signal(object, object)
    finished = Signal(object)
    failed = Signal(object)


class Programs(QObject):
    """`statuses_changed` fires after a program was checked, located, forgotten or installed, for the window's
    status bar, home card and plans."""

    changed = Signal()
    status_changed = Signal()  # the message line and the progress, which move on every downloaded block
    statuses_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()
        self._bridge: _Bridge | None = None
        self._job_name = ""
        self._on_done: Callable[[Any], None] = lambda _: None
        self._on_progress: Callable[[int, int | None], None] | None = None
        self._statuses: dict[str, DependencyStatus] = {}
        self._message = ""
        self._tone = ""
        self._progress = -1.0  # a fraction while a download knows its size, else -1
        self._cancellable = False
        self._question: dict[str, Any] = {}
        self._answer: Callable[[], None] = lambda: None
        self._focus = ""

    # What the section reads

    @Property(list, notify=changed)
    def rows(self) -> list[dict[str, Any]]:
        return [row(spec, self._statuses.get(spec.id), service.user_path(spec.id) is not None) for spec in SPECS]

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._bridge is not None

    @Property(bool, notify=status_changed)
    def cancellable(self) -> bool:
        return self._cancellable

    @Property(str, notify=status_changed)
    def message(self) -> str:
        return self._message

    @Property(str, notify=status_changed)
    def tone(self) -> str:
        return self._tone

    @Property(float, notify=status_changed)
    def progress(self) -> float:
        return self._progress

    @Property("QVariantMap", notify=changed)
    def question(self) -> dict[str, Any]:
        """The download or installer question waiting for a yes or no; empty when there is none."""
        return self._question

    @Property(str, notify=changed)
    def focus(self) -> str:
        """The program whose row a "Get it" opened the section on."""
        return self._focus

    @property
    def statuses(self) -> dict[str, DependencyStatus]:
        return dict(self._statuses)

    # Opening and closing

    @Slot(str)
    def show(self, spec_id: str = "") -> None:
        """The section opened (on `spec_id`'s row, from a "Get it"): check every program until a check came back."""
        self._focus = spec_id
        self.changed.emit()
        if not self._statuses and not self.busy:
            self.check_all()

    @Slot()
    def stop(self) -> None:
        """Settings closed: a download stops (its job removes its own staging folder) and a question waiting for an
        answer is a no. A check goes on, so the rows are there next time."""
        if self._cancellable:
            self._cancel.set()
        self.answer(False)

    # Actions

    @Slot()
    def check_all(self) -> None:
        if self.busy:
            return
        self._start(
            tr("prefs.programs.title"),
            tr("dependencies.busy.checking"),
            lambda _: service.check_all(self._cancel),
            self._on_checked,
        )

    @Slot(str)
    def locate(self, spec_id: str) -> None:
        spec = SPEC_BY_ID.get(spec_id)
        if spec is None or self.busy:
            return
        name = tr(spec.name_key)
        chosen, _ = QFileDialog.getOpenFileName(
            None,
            tr("dependencies.locate_title", name=name),
            "",
            tr("dependencies.locate_filter", name=name, pattern=file_name(spec.executables[0])),
        )
        if chosen:
            self.locate_at(spec_id, Path(chosen))

    def locate_at(self, spec_id: str, path: Path) -> None:
        service.set_user_path(spec_id, path)
        self._check_one(SPEC_BY_ID[spec_id])

    @Slot(str)
    def forget(self, spec_id: str) -> None:
        spec = SPEC_BY_ID.get(spec_id)
        if spec is not None and not self.busy:
            service.set_user_path(spec_id, None)
            self._check_one(spec)

    @Slot(str)
    def open_page(self, spec_id: str) -> None:
        spec = SPEC_BY_ID.get(spec_id)
        if spec is not None:
            QDesktopServices.openUrl(QUrl(spec.official_url))

    @Slot(str, str)
    def download(self, spec_id: str, variant_id: str = "") -> None:
        spec = SPEC_BY_ID.get(spec_id)
        if spec is None or self.busy:
            return
        name = tr(spec.name_key)
        self._say("")
        self._start(
            name,
            tr("dependencies.busy.resolving", name=name),
            lambda _: service.plan_download(spec_id, variant_id or None),
            lambda plan: self._confirm_download(spec, plan),
        )

    @Slot()
    def cancel(self) -> None:
        self._cancel.set()

    @Slot(bool)
    def answer(self, yes: bool) -> None:
        """The answer to `question`: a yes goes ahead, a no leaves things as they are."""
        if not self._question:
            return
        go, no = self._answer, self._question.get("no", "")
        self._question = {}
        self._answer = lambda: None
        if yes:
            go()
        else:
            self._say(no)

    # Jobs

    def _start(
        self,
        name: str,
        message: str,
        work: Callable[[Callable[[int, int | None], None]], Any],
        on_done: Callable[[Any], None],
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> None:
        """Run `work` on a pool thread; `on_done` and `on_progress` are called on the GUI thread."""
        self._cancel.clear()
        self._job_name = name
        self._on_done = on_done
        self._on_progress = on_progress
        bridge = _Bridge()
        self._bridge = bridge
        # Bound methods, not lambdas: Qt then knows the receiver and drops the signal once it is gone.
        bridge.finished.connect(self._finish)
        bridge.failed.connect(self._on_failed)
        bridge.progress.connect(self._report_progress)
        self._message, self._tone = message, "muted"
        self._progress = -1.0
        self._cancellable = on_progress is not None
        self.changed.emit()
        self.status_changed.emit()

        def job() -> None:
            try:
                try:
                    result = work(bridge.progress.emit)
                except Exception as error:  # anything a job raises is shown, never lost on the pool thread
                    bridge.failed.emit(error)
                else:
                    bridge.finished.emit(result)
            except RuntimeError:
                pass  # the application ended before the job: there is no one left to tell

        QThreadPool.globalInstance().start(job)

    def _idle(self) -> None:
        self._bridge = None
        self._cancellable = False
        self._progress = -1.0

    def _finish(self, result: Any) -> None:
        self._idle()
        self._on_done(result)
        self.changed.emit()
        self.status_changed.emit()

    def _report_progress(self, done: int, total: int | None) -> None:
        if self._on_progress is not None:
            self._on_progress(done, total)
            self.status_changed.emit()

    def _on_failed(self, error: Exception) -> None:
        self._idle()
        if isinstance(error, InstallCancelledError):
            self._say(tr("dependencies.cancelled"))
        else:
            self._say(tr("dependencies.failed", name=self._job_name, error=error), "drop")

    def _say(self, text: str, tone: str = "muted") -> None:
        self._message, self._tone = text, tone
        self.changed.emit()
        self.status_changed.emit()

    def _show(self, statuses: dict[str, DependencyStatus]) -> None:
        self._statuses.update(statuses)
        self.statuses_changed.emit()
        self.changed.emit()

    def _on_checked(self, statuses: dict[str, DependencyStatus]) -> None:
        self._message = ""
        self._show(statuses)

    def _check_one(self, spec: DependencySpec) -> None:
        self._start(
            tr(spec.name_key),
            tr("dependencies.busy.checking"),
            lambda _: service.check(spec, self._cancel),
            lambda status: self._on_one(spec, status),
        )

    def _on_one(self, spec: DependencySpec, status: DependencyStatus) -> None:
        self._message = ""
        self._show({spec.id: status})

    def _ask(self, title: str, text: str, no: str, go: Callable[[], None]) -> None:
        self._question = {"title": title, "text": text, "no": no}
        self._answer = go
        self.changed.emit()

    def _confirm_download(self, spec: DependencySpec, plan: DownloadPlan) -> None:
        name = tr(spec.name_key)
        host = urlsplit(plan.assets[0].url).hostname or ""
        size = plan.total_size
        values = {"name": name, "version": plan.version, "host": host}
        if plan.variant.archive is Archive.INSTALLER:
            text = tr("dependencies.confirm_installer", size=_megabytes(size or 0), **values)
        elif size is None:
            text = tr("dependencies.confirm_download_unknown", **values)
        else:
            text = tr("dependencies.confirm_download", size=_megabytes(size), **values)
        self._message = ""
        self._ask(tr("dependencies.confirm_title", name=name), text, "", lambda: self._fetch(spec, plan))

    def _fetch(self, spec: DependencySpec, plan: DownloadPlan) -> None:
        name = tr(spec.name_key)

        def report(done: int, total: int | None) -> None:
            if total:
                self._progress = done / total
                self._message = tr(
                    "dependencies.busy.downloading_of", name=name, done=_megabytes(done), total=_megabytes(total)
                )
            else:
                self._message = tr("dependencies.busy.downloading", name=name, done=_megabytes(done))

        start = tr("dependencies.busy.downloading", name=name, done=_megabytes(0))
        if plan.variant.archive is Archive.INSTALLER:
            self._start(
                name,
                start,
                lambda emit: service.download_installer(plan, emit, self._cancel),
                lambda path: self._offer_installer(spec, path),
                report,
            )
        else:
            self._start(
                name,
                start,
                lambda emit: service.install(plan, emit, self._cancel),
                lambda status: self._on_installed(spec, status),
                report,
            )

    def _on_installed(self, spec: DependencySpec, status: DependencyStatus) -> None:
        self._show({spec.id: status})
        self._say(tr("dependencies.installed", name=tr(spec.name_key), version=status.version or ""), "add")

    def _offer_installer(self, spec: DependencySpec, path: Path) -> None:
        name = tr(spec.name_key)
        self._message = ""

        def start() -> None:
            try:
                service.start_installer(path)
            except ProcessError as error:
                self._say(tr("dependencies.failed", name=name, error=error), "drop")
                return
            self._say(tr("dependencies.installer_started"))

        kept = tr("dependencies.installer_kept", path=path)
        self._ask(tr("dependencies.start_installer_title"), tr("dependencies.start_installer", name=name), kept, start)
