"""The application's main window: an empty state until a library is loaded, then the library and the sheet."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QWidget,
)

from showrunner.app.library.library import LibraryLoad
from showrunner.app.library.loader import BackgroundJob, LibraryLoader
from showrunner.app.library.service import reading_statuses
from showrunner.app.settings.app_settings import load_settings, save_settings
from showrunner.core.media import SubtitleFile
from showrunner.stages.scan.extensions import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS
from showrunner.tools.dependencies.detect import DependencyStatus
from showrunner.ui.dialogs.appearance import AppearanceDialog
from showrunner.ui.dialogs.dependencies import DependenciesDialog
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.model import Kind, LibraryModel
from showrunner.ui.library.panel import LibraryPanel
from showrunner.ui.sheet.sheet import Sheet
from showrunner.ui.shell.empty_state import EmptyState
from showrunner.ui.shell.loading import LoadingView
from showrunner.ui.shell.splitter import SavedSplitter
from showrunner.ui.shell.status import JobBar, SummaryBar
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
    ) -> None:
        super().__init__()
        self._theme = theme
        self._loader = loader or LibraryLoader(parent=self)
        self._reader_statuses = reader_statuses
        self._status_job: BackgroundJob | None = None
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
        file_menu.addAction(tr("main_window.action.exit")).triggered.connect(self.close)
        view_menu = self.menuBar().addMenu(tr("main_window.menu.view"))
        self.appearance_action = view_menu.addAction(tr("main_window.action.appearance"))
        self.appearance_action.triggered.connect(self.open_appearance)
        tools_menu = self.menuBar().addMenu(tr("main_window.menu.tools"))
        self.dependencies_action = tools_menu.addAction(tr("main_window.action.dependencies"))
        self.dependencies_action.triggered.connect(self.open_dependencies)

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
        self.addToolBar(toolbar)

    def _build_pages(self) -> None:
        self.model = LibraryModel(self)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.empty = EmptyState()
        self.empty.choose_folder.connect(self.choose_folder)
        self.empty.choose_files.connect(self.choose_files)
        self.empty.open_dependencies.connect(self.open_dependencies)
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
        self.job.cancel_requested.connect(self._cancel_load)
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

    def _cancel_load(self) -> None:
        self.job.cancelling(tr("status.cancelling"))
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
        if current is not None:
            self.panel.select(self.model.index_for_path(current))
        self.show_selection()

    # Selection and the sheet

    def show_selection(self) -> None:
        """Show the selected row on the sheet: a video in detail, a show, season or the movies as a group."""
        index = self.panel.current_source_index()
        if not index.isValid():
            self.sheet.show_placeholder()
            return
        library = self.model.library
        if self.model.kind(index) in (Kind.EPISODE, Kind.MOVIE):
            self.sheet.show_item(library, self.model.path(index))
        else:
            self.sheet.show_group(index.siblingAtColumn(0).data(), library, self.model.video_paths(index))

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
        self.summary.set_counts(self.model.library.counts())

    # Programs

    def refresh_programs(self) -> None:
        """Detect the programs that read tracks on a pool thread and show the result in the empty state."""
        job = BackgroundJob(self._reader_statuses)
        job.finished.connect(self.empty.set_statuses)
        self._status_job = job
        job.start()

    def open_appearance(self) -> None:
        dialog = AppearanceDialog(self._theme, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.exec()

    def open_dependencies(self) -> None:
        dialog = DependenciesDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.exec()
        self.refresh_programs()

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
        self._loader.cancel()
        try:
            saved = load_settings().value
            sizes = {
                "library_splitter": self.splitter.saved_sizes() or saved.library_splitter,
                "sheet_splitter": self.sheet.splitter.saved_sizes() or saved.sheet_splitter,
            }
            save_settings(replace(saved, **sizes))
        except OSError:
            _log.exception("Could not save the pane sizes")
        super().closeEvent(event)
