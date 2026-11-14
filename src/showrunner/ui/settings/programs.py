"""The Programs page: every external program with its status, and the actions to locate, download or look it up.

Checking and downloading run on a pool thread; results come back through signals, which Qt delivers on
the UI thread, so the window keeps painting and Cancel stays clickable.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.dependencies import service
from showrunner.tools.dependencies.detect import DependencyStatus, State, file_name
from showrunner.tools.dependencies.install import DownloadPlan, InstallCancelledError
from showrunner.tools.dependencies.specs import SPECS, Archive, DependencySpec
from showrunner.tools.process import ProcessError
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.theme.tokens import SIZES

# Progress bars count in ints; byte counts of large downloads do not fit, so the bar counts in thousandths.
_PROGRESS_STEPS = 1000
_STATE_ROLE = {State.OUTDATED: "notice", State.BROKEN: "danger", State.MISSING: "danger"}


def _megabytes(size: int) -> str:
    return tr("common.size_mb", value=f"{size / 1_000_000:,.1f}")


class _Bridge(QObject):
    """Carries a background job's results to the UI thread.

    It has no parent on purpose: the job keeps it alive, so a job that ends after the dialog closed
    emits into an object that still exists, and Qt drops the signals whose receiver is gone.
    """

    progress = Signal(object, object)
    finished = Signal(object)
    failed = Signal(object)


class _Row(QFrame):
    def __init__(self, spec: DependencySpec, dialog: ProgramsPage) -> None:
        super().__init__()
        self.spec = spec
        self.setProperty("role", "page")
        layout = QVBoxLayout(self)
        layout.setSpacing(SIZES["space_sm"])
        layout.setContentsMargins(*[SIZES["space_lg"]] * 4)

        top = QHBoxLayout()
        top.setSpacing(SIZES["space_md"])
        name = QLabel(tr(spec.name_key))
        name.setProperty("heading", True)
        self.state = QLabel(tr("dependencies.state.checking"))
        top.addWidget(name)
        top.addStretch()
        top.addWidget(self.state)
        layout.addLayout(top)

        self.details = QLabel()
        self.details.setProperty("role", "muted")
        self.details.setWordWrap(True)
        # A long path has no place to wrap; without this it would widen the whole page.
        self.details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)
        features = tr("common.list_separator").join(tr(f"feature.{f.value}") for f in spec.features)
        unlocks = QLabel(tr("dependencies.unlocks", features=features))
        unlocks.setWordWrap(True)
        layout.addWidget(unlocks)

        buttons = QHBoxLayout()
        buttons.setSpacing(SIZES["space_md"])
        self.locate = QPushButton(tr("dependencies.locate"))
        self.locate.clicked.connect(lambda: dialog.locate(spec))
        self.forget = QPushButton(tr("dependencies.forget"))
        self.forget.setToolTip(tr("dependencies.forget_tip"))
        self.forget.clicked.connect(lambda: dialog.forget(spec))
        self.download = QPushButton(tr("dependencies.download"))
        variants = spec.source.variants
        if len(variants) > 1:
            menu = QMenu(self.download)
            for variant in variants:
                action = menu.addAction(tr(f"dependencies.variant.{variant.id}"))
                action.triggered.connect(lambda _=False, v=variant.id: dialog.download(spec, v))
            self.download.setMenu(menu)
        else:
            self.download.clicked.connect(lambda: dialog.download(spec, None))
        page = QPushButton(tr("dependencies.official_page"))
        page.setToolTip(spec.official_url)
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(spec.official_url)))
        for button in (self.locate, self.forget, self.download, page):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.forget.hide()

    def show_status(self, status: DependencyStatus, has_user_path: bool) -> None:
        if status.state is State.OUTDATED:
            text = tr("dependencies.state.outdated", version=self.spec.min_version)
        else:
            text = tr(f"dependencies.state.{status.state.value}")
        self.state.setText(text)
        self.state.setProperty("role", _STATE_ROLE.get(status.state, ""))
        # A changed dynamic property takes effect only once the style is applied again.
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        lines = []
        if status.path is not None:
            version = (
                tr("dependencies.version", version=status.version) if status.version else tr("dependencies.no_version")
            )
            location = tr(f"dependencies.location.{status.location.value}") if status.location else ""
            lines += [tr("dependencies.version_location", version=version, location=location), str(status.path)]
        if status.state is State.BROKEN and status.detail:
            lines.append(status.detail.splitlines()[0])
        self.details.setText("\n".join(lines))
        self.details.setToolTip("" if status.path is None else str(status.path))
        self.details.setVisible(bool(lines))
        self.download.setText(tr("dependencies.download" if status.state is State.MISSING else "dependencies.update"))
        self.forget.setVisible(has_user_path)


class ProgramsPage(QWidget):
    """`programs_changed` fires after a program was checked, located, forgotten or installed."""

    programs_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()
        self._bridge: _Bridge | None = None
        self._job_name = ""
        self._on_done: Callable[[Any], None] = lambda _: None
        self._on_progress: Callable[[int, int | None], None] | None = None
        self.statuses: dict[str, DependencyStatus] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(SIZES["space_lg"])
        layout.setContentsMargins(0, 0, 0, 0)

        rows = QWidget()
        rows_layout = QVBoxLayout(rows)
        rows_layout.setSpacing(SIZES["space_md"])
        rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows = {spec.id: _Row(spec, self) for spec in SPECS}
        for row in self.rows.values():
            rows_layout.addWidget(row)
        rows_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(rows)
        layout.addWidget(scroll, 1)

        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.setSpacing(SIZES["space_md"])
        self.cancel_button = QPushButton(tr("common.cancel"))
        self.cancel_button.clicked.connect(self._cancel.set)
        self.cancel_button.hide()
        self.recheck_button = QPushButton(tr("dependencies.recheck"))
        self.recheck_button.clicked.connect(self.check_all)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        buttons.addWidget(self.recheck_button)
        layout.addLayout(buttons)

        self.check_all()

    # Background jobs

    @property
    def busy(self) -> bool:
        return self._bridge is not None

    def _start(
        self,
        name: str,
        message: str,
        work: Callable[[Callable[[int, int | None], None]], Any],
        on_done: Callable[[Any], None],
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> None:
        """Run `work` on a pool thread; `on_done` and `on_progress` are called on the UI thread."""
        self._cancel.clear()
        self._job_name = name
        self._on_done = on_done
        self._on_progress = on_progress
        bridge = _Bridge()
        self._bridge = bridge
        # Bound methods of the dialog, not lambdas: Qt then knows the receiver, delivers on its thread,
        # and drops the signal if the dialog was deleted before the job ended.
        bridge.finished.connect(self._finish)
        bridge.failed.connect(self._on_failed)
        bridge.progress.connect(self._report_progress)
        self._set_busy(message, cancellable=on_progress is not None)

        def job() -> None:
            try:
                result = work(bridge.progress.emit)
            except Exception as error:  # anything a job raises is shown, never lost on the pool thread
                bridge.failed.emit(error)
            else:
                bridge.finished.emit(result)

        QThreadPool.globalInstance().start(job)

    def _set_busy(self, message: str, cancellable: bool) -> None:
        self.message.setProperty("role", "muted")
        self._repolish(self.message)
        self.message.setText(message)
        self.progress.setRange(0, 0)
        self.progress.setVisible(cancellable)
        self.cancel_button.setVisible(cancellable)
        self.recheck_button.setEnabled(False)
        for row in self.rows.values():
            for button in (row.locate, row.forget, row.download):
                button.setEnabled(False)

    def _finish(self, result: Any) -> None:
        self._idle()
        self._on_done(result)

    def _report_progress(self, done: int, total: int | None) -> None:
        if self._on_progress is not None:
            self._on_progress(done, total)

    def _idle(self) -> None:
        self._bridge = None
        self.progress.hide()
        self.cancel_button.hide()
        self.recheck_button.setEnabled(True)
        for row in self.rows.values():
            for button in (row.locate, row.forget, row.download):
                button.setEnabled(True)

    def _on_failed(self, error: Exception) -> None:
        self._idle()
        if isinstance(error, InstallCancelledError):
            self._say(tr("dependencies.cancelled"))
        else:
            self._say(tr("dependencies.failed", name=self._job_name, error=error), role="danger")

    def _say(self, text: str, role: str = "") -> None:
        self.message.setProperty("role", role)
        self._repolish(self.message)
        self.message.setText(text)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _show(self, statuses: dict[str, DependencyStatus]) -> None:
        self.statuses.update(statuses)
        self.programs_changed.emit()
        for spec_id, status in statuses.items():
            self.rows[spec_id].show_status(status, service.user_path(spec_id) is not None)

    def stop(self) -> None:
        """Stop a running download; the job then removes its own staging folder."""
        self._cancel.set()

    # Actions

    def check_all(self) -> None:
        self._say("")
        self._start(
            tr("settings.page.programs"),
            tr("dependencies.busy.checking"),
            lambda _: service.check_all(self._cancel),
            self._on_checked,
        )

    def _on_checked(self, statuses: dict[str, DependencyStatus]) -> None:
        self._say("")
        self._show(statuses)

    def _check_one(self, spec: DependencySpec) -> None:
        def done(status: DependencyStatus) -> None:
            self._show({spec.id: status})

        checking = tr("dependencies.busy.checking")
        self._start(tr(spec.name_key), checking, lambda _: service.check(spec, self._cancel), done)

    def locate(self, spec: DependencySpec) -> None:
        first = file_name(spec.executables[0])
        name = tr(spec.name_key)
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            tr("dependencies.locate_title", name=name),
            "",
            tr("dependencies.locate_filter", name=name, pattern=first),
        )
        if not chosen:
            return
        service.set_user_path(spec.id, Path(chosen))
        self._check_one(spec)

    def forget(self, spec: DependencySpec) -> None:
        service.set_user_path(spec.id, None)
        self._check_one(spec)

    def download(self, spec: DependencySpec, variant_id: str | None) -> None:
        name = tr(spec.name_key)
        self._say("")
        self._start(
            name,
            tr("dependencies.busy.resolving", name=name),
            lambda _: service.plan_download(spec.id, variant_id),
            lambda plan: self._confirm_download(spec, plan),
        )

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
        answer = QMessageBox.question(self, tr("dependencies.confirm_title", name=name), text)
        if answer != QMessageBox.StandardButton.Yes:
            return

        def report(done: int, total: int | None) -> None:
            if total:
                self.progress.setRange(0, _PROGRESS_STEPS)
                self.progress.setValue(int(done * _PROGRESS_STEPS / total))
                text = tr("dependencies.busy.downloading_of", name=name, done=_megabytes(done), total=_megabytes(total))
            else:
                text = tr("dependencies.busy.downloading", name=name, done=_megabytes(done))
            self.message.setText(text)

        if plan.variant.archive is Archive.INSTALLER:
            self._start(
                name,
                text,
                lambda emit: service.download_installer(plan, emit, self._cancel),
                lambda path: self._offer_installer(spec, path),
                report,
            )
        else:
            self._start(
                name,
                text,
                lambda emit: service.install(plan, emit, self._cancel),
                lambda status: self._on_installed(spec, status),
                report,
            )

    def _on_installed(self, spec: DependencySpec, status: DependencyStatus) -> None:
        self._show({spec.id: status})
        self._say(tr("dependencies.installed", name=tr(spec.name_key), version=status.version or ""))

    def _offer_installer(self, spec: DependencySpec, path: Path) -> None:
        name = tr(spec.name_key)
        answer = QMessageBox.question(
            self, tr("dependencies.start_installer_title"), tr("dependencies.start_installer", name=name)
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._say(tr("dependencies.installer_kept", path=path))
            return
        try:
            service.start_installer(path)
        except ProcessError as error:
            self._say(tr("dependencies.failed", name=name, error=error), role="danger")
            return
        self._say(tr("dependencies.installer_started"))
