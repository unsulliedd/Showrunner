"""The application's main window: an empty state until a library is loaded, then the library and the sheet."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QWidget,
)

from showrunner.app.jobs.preview import FileOutcome, FilePreview
from showrunner.app.jobs.run import JobResult
from showrunner.app.jobs.stages import PlanState
from showrunner.app.jobs.store import JobStore, JobSummary, StepState, UnresumableJobError
from showrunner.app.library.library import LibraryLoad
from showrunner.app.library.loader import BackgroundJob, LibraryLoader
from showrunner.app.library.service import reading_statuses
from showrunner.app.profiles.store import ProfileStore
from showrunner.app.settings.app_settings import Startup, load_settings, save_settings
from showrunner.app.storage.paths import jobs_path
from showrunner.core.media import SubtitleFile
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.scan.extensions import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS
from showrunner.stages.tracks import TrackPlan
from showrunner.tools.dependencies.detect import DependencyStatus
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.library.model import Kind, LibraryModel
from showrunner.ui.library.panel import LibraryPanel
from showrunner.ui.settings.general import Workspace
from showrunner.ui.settings.profiles import settle_unsaved
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.settings.window import SettingsWindow
from showrunner.ui.sheet.format import item_title
from showrunner.ui.sheet.sheet import Sheet
from showrunner.ui.sheet.tracks import TablePlan
from showrunner.ui.shell.empty_state import EmptyState
from showrunner.ui.shell.loading import LoadingView
from showrunner.ui.shell.splitter import SavedSplitter
from showrunner.ui.shell.status import JobBar, SummaryBar
from showrunner.ui.stages.bar import StageBar
from showrunner.ui.stages.controller import Pipeline, StageController, default_pipeline
from showrunner.ui.stages.plan_view import PlannedChanges, state_of
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES

_log = logging.getLogger(__name__)
_EMPTY_PAGE = 0
_LOADED_PAGE = 1
_LOADING_PAGE = 2
_MESSAGE_MS = 8000


def dropped_paths(mime: QMimeData) -> list[Path]:
    """The local files and folders in a drag or a drop."""
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]


class MainWindow(QMainWindow):
    def __init__(
        self,
        theme: ThemeManager,
        loader: LibraryLoader | None = None,
        reader_statuses: Callable[[], dict[str, DependencyStatus]] = reading_statuses,
        *,
        profiles: ProfileStore | None = None,
        jobs: JobStore | None = None,
        make_pipeline: Pipeline = default_pipeline,
    ) -> None:
        super().__init__()
        self._theme = theme
        self._loader = loader or LibraryLoader(parent=self)
        self._reader_statuses = reader_statuses
        self._status_job: BackgroundJob | None = None
        self._statuses_known = False
        self._offer_jobs = False
        self._restore_selection: Path | None = None
        self._restoring = False
        self.settings_window: SettingsWindow | None = None
        self.session = ProfileSession(profiles, self)
        self.stages = StageController(
            self.session, jobs or JobStore(jobs_path()), make_pipeline=make_pipeline, parent=self
        )
        self.stages.set_source(load_settings().value.batch_source)
        self.setWindowTitle(tr("main_window.title"))
        self.resize(SIZES["window_width"], SIZES["window_height"])
        self.setMinimumSize(SIZES["window_min_width"], SIZES["window_min_height"])
        self.setAcceptDrops(True)

        self._build_menus()
        self._build_toolbar()
        self._build_pages()
        self._build_status_bar()
        self._restore_splitters()
        self._loader.progress.connect(self._on_progress)
        self._loader.finished.connect(self._on_loaded)
        self._loader.failed.connect(self._on_load_failed)
        self.model.library_changed.connect(self.stages.library_changed)
        self.stages.changed.connect(self._on_stages_changed)
        self.stages.progress.connect(self._on_job_progress)
        self.stages.files_read.connect(self.model.replace_files)
        self.stages.applied.connect(self._on_applied)
        self.stages.failed.connect(lambda message: self.statusBar().showMessage(message, _MESSAGE_MS))
        self.empty.folder_button.setFocus()
        self.refresh_programs()

    # Construction

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(tr("main_window.menu.file"))
        self.add_folder_action = file_menu.addAction(tr("main_window.action.add_folder"))
        self.add_folder_action.triggered.connect(self.choose_folder)
        self.add_files_action = file_menu.addAction(tr("main_window.action.add_files"))
        self.add_files_action.triggered.connect(self.choose_files)
        file_menu.addSeparator()
        self.settings_action = file_menu.addAction(tr("main_window.action.settings"))
        self.settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        if self.settings_action.shortcut().isEmpty():
            self.settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self.settings_action.triggered.connect(lambda: self.open_settings())
        file_menu.addSeparator()
        file_menu.addAction(tr("main_window.action.exit")).triggered.connect(self.close)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        toolbar.setContentsMargins(SIZES["space_md"], 0, SIZES["space_md"], 0)
        self.add_button = QPushButton(tr("main_window.action.add_folder"))
        self.add_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.add_button.clicked.connect(self.choose_folder)
        toolbar.addWidget(self.add_button)
        self.stage_bar = StageBar(self.session, self.stages, self._theme)
        self.stage_bar.open_page.connect(self.open_settings)
        self.stage_bar.preview_requested.connect(self.preview)
        self.stage_bar.apply_requested.connect(self.apply)
        self.stage_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(self.stage_bar)
        self.addToolBar(toolbar)

    def _build_pages(self) -> None:
        self.model = LibraryModel(self)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.empty = EmptyState()
        self.empty.choose_folder.connect(self.choose_folder)
        self.empty.choose_files.connect(self.choose_files)
        self.empty.open_dependencies.connect(lambda: self.open_settings("programs"))
        self.stack.addWidget(self._framed(self.empty, left=SIZES["space_md"]))

        self.panel = LibraryPanel(self.model, self._theme)
        self.panel.setMinimumWidth(SIZES["library_min_width"])
        self.panel.selection_changed.connect(lambda _index: self.show_selection())
        self.sheet = Sheet(self._theme)
        self.sheet.unpair_requested.connect(self._unpair)
        self.sheet.pair_instead_requested.connect(self._pair_instead)
        self.sheet.pair_here_requested.connect(self._pair_here)
        self.splitter = SavedSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(SIZES["space_md"])
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.panel)
        self.splitter.addWidget(self.sheet)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.stack.addWidget(self._framed(self.splitter, left=0))

        self.loading_view = LoadingView()
        self.stack.addWidget(self._framed(self.loading_view, left=SIZES["space_md"]))

    @staticmethod
    def _framed(content: QWidget, *, left: int) -> QWidget:
        """The inset of a page: the toolbar sits directly above it, so there is no top margin."""
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(left, 0, SIZES["space_md"], SIZES["space_md"])
        layout.addWidget(content)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return page

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        bar.setContentsMargins(SIZES["space_lg"], 0, SIZES["space_lg"], 0)
        self.summary = SummaryBar()
        self.job = JobBar()
        self.job.cancel_requested.connect(self._cancel)
        bar.addWidget(self.summary, 1)
        bar.addPermanentWidget(self.job)
        self.model.library_changed.connect(self._update_summary)

    def _restore_splitters(self) -> None:
        saved = load_settings().value
        if saved.library_splitter:
            self.splitter.restore(saved.library_splitter)
        else:
            self.splitter.restore(
                [SIZES["library_width"], SIZES["window_width"] - SIZES["library_width"]], default=True
            )
        if saved.sheet_splitter:
            self.sheet.splitter.restore(saved.sheet_splitter)

    # Loading

    @property
    def loading(self) -> bool:
        return self._loader.busy

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("main_window.choose_folder"))
        if folder:
            self.add_paths([Path(folder)])

    def choose_files(self) -> None:
        pattern = " ".join(f"*{extension}" for extension in sorted(VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("main_window.choose_files"), "", tr("main_window.files_filter", pattern=pattern)
        )
        if files:
            self.add_paths([Path(f) for f in files])

    def add_paths(self, paths: list[Path]) -> None:
        """Scan the paths and add what they hold to the library."""
        if self._loader.busy or not paths:
            return
        self.statusBar().clearMessage()
        self.job.start(tr("status.scanning"))
        self.loading_view.set_detail(tr("status.scanning"))
        if self.stack.currentIndex() == _EMPTY_PAGE:
            self.stack.setCurrentIndex(_LOADING_PAGE)
        self._set_loading(True)
        self._loader.start(paths, known=[i.file.path for i in self.model.library.items])

    def _set_loading(self, loading: bool) -> None:
        for action in (self.add_folder_action, self.add_files_action):
            action.setEnabled(not loading)
        self.add_button.setEnabled(not loading)
        self.job.setVisible(loading)

    def _cancel(self) -> None:
        self.job.cancelling(tr("status.cancelling"))
        if self.stages.busy:
            self.stages.cancel()
        else:
            self._loader.cancel()

    def _on_progress(self, done: int, total: int) -> None:
        text = tr("status.reading", done=done, total=total)
        self.job.report(text, done, total)
        self.loading_view.set_detail(text)

    def _leave_loading_page(self) -> None:
        """After a load that added nothing, the window goes back to what it showed before."""
        if self.stack.currentIndex() == _LOADING_PAGE:
            self.stack.setCurrentIndex(_LOADED_PAGE if self.model.library.items else _EMPTY_PAGE)

    def _on_load_failed(self, error: Exception) -> None:
        self._set_loading(False)
        self._leave_loading_page()
        self.statusBar().showMessage(tr("status.load_failed", error=error), _MESSAGE_MS)

    def _on_loaded(self, load: LibraryLoad) -> None:
        self._set_loading(False)
        restoring, self._restoring = self._restoring, False
        if restoring and load.cancelled:
            self._restore_selection = None
            self._leave_loading_page()
            return
        if not load.items:
            self._leave_loading_page()
            self.statusBar().showMessage(tr("status.nothing_new"), _MESSAGE_MS)
            return
        if load.cancelled:
            self.statusBar().showMessage(tr("status.cancelled"), _MESSAGE_MS)
        shown = self.stack.currentIndex() == _LOADED_PAGE
        current = self.model.path(self.panel.current_source_index()) if shown else None
        self.model.add(load)
        self.panel.expand_default()
        self.stack.setCurrentIndex(_LOADED_PAGE)
        current = current or self._restore_selection
        self._restore_selection = None
        if current is not None and self.model.index_for_path(current).isValid():
            self.panel.select(self.model.index_for_path(current))
        self.show_selection()

    # Selection and the sheet

    def show_selection(self) -> None:
        """Show the selected row on the sheet: a video in detail, a show, season or the movies as a group."""
        index = self.panel.current_source_index()
        path = self.model.path(index) if index.isValid() else None
        if self.settings_window is not None:
            self.settings_window.set_item(self.model.library.item(path) if path else None)
        if not index.isValid():
            self.sheet.show_placeholder()
            return
        library = self.model.library
        if self.model.kind(index) not in (Kind.EPISODE, Kind.MOVIE):
            self.sheet.show_group(index.siblingAtColumn(0).data(), library, self.model.video_paths(index))
            return
        file = self.stages.file(path)
        if file is None:
            self.sheet.show_item(library, path)
            return
        plan = PlannedChanges(self._theme)
        plan.show_file(
            file, self.session.blocks(), current=self.stages.is_current, left_out=path in self.stages.left_out
        )
        plan.open_page.connect(self._open_from_plan)
        plan.open_rule.connect(self.open_rule)
        plan.leave_out.connect(lambda out: self.stages.leave_out(path, out))
        self.sheet.show_item(library, path, plan=plan, table_plan=self._table_plan(file), state=state_of(file))

    def _table_plan(self, file: FilePreview) -> TablePlan:
        tracks = file.plan_for("tracks")
        metadata = file.plan_for("metadata")
        track_plan = tracks.plan if tracks is not None and isinstance(tracks.plan, TrackPlan) else None
        names = {}
        if metadata is not None and isinstance(metadata.plan, MetadataPlan):
            names = {c.track_id: str(c.new) for c in metadata.plan.changes if c.prop is Property.NAME}
        return TablePlan(track_plan, names, self._theme.roles)

    def _open_from_plan(self, page: str) -> None:
        if page:
            self.open_settings(page)
        else:
            self.session.update("metadata", enabled=True)

    def _unpair(self, subtitle: SubtitleFile) -> None:
        self.model.unpair(subtitle)
        self.show_selection()

    def _pair_instead(self, video: Path, subtitle: SubtitleFile) -> None:
        self.model.pair_instead(video, subtitle)
        self.show_selection()

    def _pair_here(self, subtitle: SubtitleFile, video: Path) -> None:
        self.model.pair(subtitle, video)
        self.show_selection()

    def _update_summary(self) -> None:
        counts = self.model.library.counts()
        preview = self.stages.preview
        if preview is None or counts.videos == 0:
            self.summary.set_counts(counts)
            return
        outcomes = [f.outcome for f in preview.files]
        parts = [(tr_plural("preview.summary", len(outcomes)), "")]
        for outcome, role in (
            (FileOutcome.CHANGES, ""),
            (FileOutcome.REFUSED, "notice"),
            (FileOutcome.NEEDS_REMUX, "notice"),
            (FileOutcome.UNWRITTEN, "notice"),
            (FileOutcome.UNCHANGED, ""),
            (FileOutcome.MISSING, "danger"),
        ):
            if number := outcomes.count(outcome):
                parts.append((tr_plural(f"preview.outcome.{outcome.value}", number), role))
        if counts.unsure:
            parts.append((tr_plural("summary.unsure", counts.unsure), "notice"))
        if counts.failed:
            parts.append((tr_plural("summary.failed", counts.failed), "danger"))
        blocked = dict.fromkeys(p.stage for f in preview.files for p in f.plans if p.state is PlanState.BLOCKED)
        for stage_id in blocked:
            block = self.session.blocks().get(stage_id)
            page = tr("settings.page.naming" if stage_id == "metadata" else "settings.page.tracks")
            count = block.count if block else 1
            parts.append((tr_plural("preview.blocked", count, stage=tr(f"stage.{stage_id}"), page=page), "danger"))
        self.summary.set_parts(parts)

    # Preview and Apply

    def preview(self) -> None:
        if not self.model.library.items or self.stages.busy:
            return
        self.job.start(tr("preview.running"))
        self.job.cancel.setEnabled(False)
        self.stages.start_preview(self.model.library.items)

    def confirm_apply(self, files: int, remuxed: int) -> bool:
        """Asked once before Apply; replaced in tests."""
        text = tr_plural("preview.confirm_text", files)
        if remuxed:
            text += " " + tr_plural("preview.confirm_remux", remuxed)
        answer = QMessageBox.question(self, tr("preview.confirm_title"), text)
        return answer == QMessageBox.StandardButton.Yes

    def apply(self) -> None:
        files = self.stages.to_write()
        if not files or not self.stages.is_current:
            return
        remuxed = sum(any(p.needs_remux for p in f.writes) for f in files)
        if not self.confirm_apply(len(files), remuxed):
            return
        self.job.start(tr("preview.applying"))
        self.stages.apply()

    def _on_stages_changed(self) -> None:
        if not self.stages.busy and not self._loader.busy:
            self.job.hide()
        self.model.set_plan_marks(self.stages.marks())
        self._update_summary()
        self.show_selection()

    def _on_job_progress(self, done: int, total: int) -> None:
        self.job.report(tr("preview.applied_of", done=done, total=total), done, total)

    def _on_applied(self, result: JobResult) -> None:
        states = [s.state for s in result.steps]
        text = tr(
            "preview.applied",
            done=states.count(StepState.DONE),
            failed=states.count(StepState.FAILED),
            stale=states.count(StepState.STALE) + states.count(StepState.SKIPPED),
        )
        self.statusBar().showMessage(tr("preview.cancelled") if result.cancelled else text, _MESSAGE_MS)

    # Unfinished jobs

    def offer_unfinished_jobs(self) -> None:
        """Offer to resume or discard the jobs an earlier run left unfinished, once the programs are known."""
        self._offer_jobs = True
        if self._statuses_known:
            self._offer_now()

    def ask_resume(self, job: JobSummary) -> str:
        """`resume`, `discard` or `later`; replaced in tests."""
        box = QMessageBox(self)
        box.setWindowTitle(tr("jobs.title"))
        box.setText(tr("jobs.unfinished", done=job.finished, total=job.steps, profile=job.profile_name))
        resume = box.addButton(tr("jobs.resume"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(tr("jobs.discard"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("jobs.later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return "resume" if box.clickedButton() is resume else "discard" if box.clickedButton() is discard else "later"

    def ask_discard_unresumable(self, job: JobSummary) -> bool:
        """Whether to forget a job that cannot be resumed; replaced in tests."""
        text = tr("jobs.unresumable", done=job.finished, total=job.steps)
        return QMessageBox.question(self, tr("jobs.title"), text) == QMessageBox.StandardButton.Yes

    def _offer_now(self) -> None:
        self._offer_jobs = False
        store = self.stages.store
        for job in store.unfinished():
            try:
                store.load(job.id)
            except UnresumableJobError:
                if self.ask_discard_unresumable(job):
                    store.discard(job.id)
                continue
            answer = self.ask_resume(job)
            if answer == "discard":
                store.discard(job.id)
            elif answer == "resume" and not self.stages.busy:
                self.job.start(tr("preview.applying"))
                self.stages.run(job.id)

    # The workspace

    def restore_workspace(self) -> None:
        """Read the last folders again when the user chose to start that way."""
        settings = load_settings().value
        if settings.startup is not Startup.LAST_WORKSPACE:
            return
        folders = [Path(f) for f in settings.last_folders if Path(f).is_dir()]
        if not folders:
            return
        if settings.last_selection:
            self._restore_selection = Path(settings.last_selection)
        self._restoring = True
        self.add_paths(folders)

    def workspace(self) -> Workspace:
        index = self.panel.current_source_index()
        path = self.model.path(index) if index.isValid() else None
        item = self.model.library.item(path) if path else None
        sizes = self.splitter.sizes() or [SIZES["library_width"]]
        details = self.sheet.splitter.sizes()
        return Workspace(
            tuple(r.name for r in self.model.library.roots),
            item_title(item) if item else "",
            sizes[0],
            details[-1] if len(details) > 1 else SIZES["details_width"],
        )

    # Settings

    def open_settings(self, page: str = "general") -> None:
        if self.settings_window is None:
            window = SettingsWindow(self._theme, self.session, self.workspace, self)
            window.programs_changed.connect(self.refresh_programs)
            window.naming.source_changed.connect(self.stages.set_source)
            self.settings_window = window
            self.show_selection()
        self.settings_window.open_page(page)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def open_rule(self, index: int) -> None:
        self.open_settings("tracks")
        if self.settings_window is not None:
            self.settings_window.open_rule(index)

    # Programs

    def refresh_programs(self) -> None:
        """Detect the programs on a pool thread; the empty state and the stage switches show the result."""
        if self._status_job is not None:
            return
        job = BackgroundJob(self._reader_statuses)
        job.finished.connect(self._on_statuses)
        self._status_job = job
        job.start()

    def _on_statuses(self, statuses: dict[str, DependencyStatus]) -> None:
        self._status_job = None
        self._statuses_known = True
        self.empty.set_statuses(statuses)
        self.stages.set_statuses(statuses)
        if self._offer_jobs:
            self._offer_now()

    # Drops

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802  # Qt's name
        paths = dropped_paths(event.mimeData())
        if paths and not self._loader.busy:
            event.acceptProposedAction()
            self.empty.set_dragging(paths[0].name)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802  # Qt's name
        self.empty.set_dragging(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802  # Qt's name
        self.empty.set_dragging(None)
        paths = dropped_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.add_paths(paths)

    # Closing

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802  # Qt's name
        if not settle_unsaved(self, self.session):
            event.ignore()
            return
        self._loader.cancel()
        self.stages.cancel()
        if self.settings_window is not None:
            self.settings_window.close()
        try:
            saved = load_settings().value
            index = self.panel.current_source_index()
            selected = self.model.path(index) if index.isValid() else None
            library = self.model.library
            workspace = {
                "library_splitter": self.splitter.saved_sizes() or saved.library_splitter,
                "sheet_splitter": self.sheet.splitter.saved_sizes() or saved.sheet_splitter,
                "last_folders": [str(r) for r in library.roots] if library.items else saved.last_folders,
                "last_selection": str(selected) if selected else "",
            }
            save_settings(replace(saved, **workspace))
        except OSError:
            _log.exception("Could not save the pane sizes")
        super().closeEvent(event)
