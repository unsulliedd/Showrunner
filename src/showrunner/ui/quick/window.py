"""The controller behind the Qt Quick window: the library, the selected batch, the programs and the workspace state.

QML reads its properties and calls its slots; it holds no logic of its own. Loading, checking programs and saving
go through the app layer, and slow work runs on pool threads through `BackgroundJob`.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QByteArray, QModelIndex, QObject, QUrl, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from showrunner.app.batches.batch import Batches, BatchKey, Media
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.dependencies.service import check
from showrunner.app.library.library import LibraryLoad
from showrunner.app.library.loader import BackgroundJob, LibraryLoader
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.app.settings.app_settings import Startup, load_settings, save_settings, with_recent
from showrunner.core.media import MediaItem
from showrunner.stages.scan.extensions import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.dependencies.specs import SPEC_BY_ID
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.model import Kind, LibraryModel
from showrunner.ui.quick.facts import heading, when
from showrunner.ui.quick.library import LibraryTree
from showrunner.ui.quick.programs_dialog import run_programs_dialog

_log = logging.getLogger(__name__)

# The places of a workspace in the order of work, with their icons; `later` ones are drawn muted until their stage
# exists.
WORKSPACE_TABS: tuple[tuple[str, str, bool], ...] = (
    ("overview", "list", False),
    ("tracks", "audio", False),
    ("names", "names", False),
    ("review", "eye", False),
    ("subtitles", "subs", True),
    ("artwork", "image", True),
    ("chapters", "chapters", True),
)
# The side panel each place brings; Review takes the whole width.
SIDE_PANELS: dict[str, tuple[str, ...]] = {
    "overview": ("inspector", "chapters", "attachments"),
    "tracks": ("rules", "inspector"),
    "names": ("tokens", "inspector"),
    "review": (),
}
# The programs the first-run screen and the status bar show: the ones that read and write the files today.
SHOWN_PROGRAMS: tuple[str, ...] = ("mkvtoolnix", "ffmpeg")

type Statuses = dict[str, DependencyStatus]


def check_shown() -> Statuses:
    return {spec_id: check(SPEC_BY_ID[spec_id]) for spec_id in SHOWN_PROGRAMS}


def local_paths(urls: list[Any]) -> list[Path]:
    """The local files and folders among dropped or chosen URLs."""
    found = (QUrl(url) if isinstance(url, str) else url for url in urls)
    return [Path(url.toLocalFile()) for url in found if isinstance(url, QUrl) and url.isLocalFile()]


class WindowController(QObject):
    library_changed = Signal()
    loading_changed = Signal()
    programs_changed = Signal()
    recent_changed = Signal()
    batch_changed = Signal()
    filter_changed = Signal()

    def __init__(
        self,
        *,
        statuses: Callable[[], Statuses] = check_shown,
        loader: LibraryLoader | None = None,
        store: ProfileStore | None = None,
        get_program: Callable[[str], None] = run_programs_dialog,
        clock: Callable[[], datetime] = datetime.now,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = LibraryModel(self)
        self.tree = LibraryTree(self)
        self.tree.setSourceModel(self.model)
        self._loader = loader or LibraryLoader(parent=self)
        self._loader.progress.connect(self._on_progress)
        self._loader.finished.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._check = statuses
        self._get_program = get_program
        self._clock = clock
        self._store = store or ProfileStore()
        self.batches: Batches = load_batches(self._store)
        self._statuses: Statuses | None = None
        self._jobs: set[BackgroundJob] = set()
        self._progress: tuple[int, int] | None = None
        self._message = ""  # what the last load ended with, when it is worth saying
        self._filter = ""
        self._needs_look_only = False
        self._selected = ""  # the row id of the selected row
        self._key: BatchKey | None = None
        self._items: list[MediaItem] = []
        self._focus: MediaItem | None = None  # the selected video inside the batch
        settings = load_settings().value
        self._recent = dict(settings.recent_folders)
        self._restore = settings.last_selection
        self.model.library_changed.connect(self.library_changed)

    # Start and end

    def start(self) -> None:
        """Check the programs in the background; `restore_workspace` reads the last folders again."""
        self.refresh_programs()

    def restore_workspace(self) -> None:
        settings = load_settings().value
        if settings.startup is not Startup.LAST_WORKSPACE:
            return
        self.add_paths([Path(f) for f in settings.last_folders if Path(f).is_dir()])

    def save_workspace(self) -> None:
        """Keep what is open for the next start: the folders, the selection and each batch's working copy."""
        library = self.model.library
        saved = load_settings().value
        folders = [str(r) for r in library.roots] if library.items else saved.last_folders
        focus = str(self._focus.file.path) if self._focus is not None else saved.last_selection
        try:
            save_settings(replace(saved, last_folders=folders, last_selection=focus, recent_folders=self._recent))
            save_batches(self.batches)
        except OSError:
            _log.exception("Could not save the workspace")

    # Library

    @Property(QObject, constant=True)
    def library(self) -> LibraryTree:
        return self.tree

    @Property(bool, notify=library_changed)
    def loaded(self) -> bool:
        return bool(self.model.library.items)

    @Property(int, notify=library_changed)
    def needs_look(self) -> int:
        return self.model.needs_look_count()

    @Property(bool, notify=loading_changed)
    def busy(self) -> bool:
        return self._loader.busy

    @Property(str, notify=loading_changed)
    def job_text(self) -> str:
        if self._progress is not None:
            done, total = self._progress
            return tr("status.reading", done=done, total=total)
        if self._loader.busy:
            return tr("status.scanning")
        return self._message or tr("statusbar.no_jobs")

    def _get_filter(self) -> str:
        return self._filter

    def _set_filter(self, text: str) -> None:
        if text != self._filter:
            self._filter = text
            self.tree.set_text(text)
            self.filter_changed.emit()

    filter_text = Property(str, _get_filter, _set_filter, notify=filter_changed)

    def _get_needs_look_only(self) -> bool:
        return self._needs_look_only

    def _set_needs_look_only(self, enabled: bool) -> None:
        if enabled != self._needs_look_only:
            self._needs_look_only = enabled
            self.tree.set_needs_look(enabled)
            self.filter_changed.emit()

    needs_look_only = Property(bool, _get_needs_look_only, _set_needs_look_only, notify=filter_changed)

    @Slot()
    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, tr("home.choose_folder"))
        if folder:
            self.add_paths([Path(folder)])

    @Slot()
    def choose_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(None, tr("home.choose_files"), "", f"{tr('home.files')} ({patterns})")
        self.add_paths([Path(f) for f in files])

    @Slot(list)
    def add_urls(self, urls: list[Any]) -> None:
        self.add_paths(local_paths(urls))

    @Slot(str)
    def open_recent(self, folder: str) -> None:
        self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]) -> None:
        # A second drop while reading is ignored: the loader runs one load at a time.
        if not paths or self._loader.busy:
            return
        self._message = ""
        self._loader.start(paths, known=[item.file.path for item in self.model.library.items])
        self.loading_changed.emit()

    def _on_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)
        self.loading_changed.emit()

    def _on_failed(self, error: Exception) -> None:
        _log.error("Loading failed: %s", error)
        self._progress = None
        self._message = tr("status.load_failed", error=error)
        self.loading_changed.emit()

    def _on_loaded(self, load: LibraryLoad) -> None:
        self._progress = None
        self._message = tr("status.nothing_new") if not load.items and not load.cancelled else ""
        self.model.add(load)
        if load.roots:
            self._recent = with_recent(self._recent, [str(root) for root in load.roots], self._clock())
            self.recent_changed.emit()
        current = self.tree.index_of(self._selected) if self._selected else QModelIndex()
        # Selected again even when it stays, since a season or show may have gained videos.
        if current.isValid():
            self.select(current)
        else:
            self._select_first()
        self.loading_changed.emit()

    def _select_first(self) -> None:
        """The video selected when the window last closed, else the first row of the tree."""
        restored = self.tree.index_of(self._restore) if self._restore else QModelIndex()
        self.select(restored if restored.isValid() else self.tree.index(0, 0))

    # Selection and batch

    @Slot(QModelIndex)
    def select(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        self._selected = self.tree.row_id(index)
        source = self.tree.mapToSource(index)
        paths = self.model.video_paths(source)
        items = [item for path in paths if (item := self.model.library.item(path)) is not None]
        kind = self.model.kind(source)
        self._focus = items[0] if kind.is_video and items else None
        if not items:
            self._key, self._items = None, []
        elif kind is Kind.EPISODE:
            self._key = BatchKey.of(items[0])
            self._items = [i for i in self.model.library.items if BatchKey.of(i) == self._key]
        elif kind in (Kind.SEASON, Kind.MOVIE):
            self._key, self._items = BatchKey.of(items[0]), items
        elif kind is Kind.SHOW:
            self._key, self._items = BatchKey.of(items[0], whole_show=True), items
        else:
            self._key, self._items = BatchKey.selection(paths, Media.MOVIES), items
        self.batch_changed.emit()

    @Property(str, notify=batch_changed)
    def selected(self) -> str:
        return self._selected

    @Property(QModelIndex, notify=batch_changed)
    def selected_index(self) -> QModelIndex:
        """The selected row in the tree as filtered now; invalid when the filter hides it."""
        return self.tree.index_of(self._selected) if self._selected else QModelIndex()

    @Property(bool, notify=batch_changed)
    def has_batch(self) -> bool:
        return self._key is not None

    @Property(str, notify=batch_changed)
    def batch_kind(self) -> str:
        return self._key.kind.value if self._key is not None else ""

    @Property("QVariantMap", notify=batch_changed)
    def batch(self) -> dict[str, str]:
        if self._key is None:
            return {"over": "", "title": "", "facts": ""}
        head = heading(self._key, self._items)
        return {"over": head.over, "title": head.title, "facts": head.facts}

    @Property(int, notify=batch_changed)
    def change_count(self) -> int:
        # Plans come with the workspace tabs that make them; until then a batch changes nothing.
        return 0

    @Property(list, notify=batch_changed)
    def workspace_tabs(self) -> list[dict[str, Any]]:
        return [{"key": key, "icon": icon, "count": 0, "later": later} for key, icon, later in WORKSPACE_TABS]

    @Slot(str, result=list)
    def side_tabs(self, place: str) -> list[dict[str, Any]]:
        """The side panel's tabs for a workspace place; Chapters and Attachments count the selected video's."""
        file = self._focus.file if self._focus is not None else (self._items[0].file if self._items else None)
        counts = {
            "chapters": len(file.chapters) if file is not None else 0,
            "attachments": len(file.attachments) if file is not None else 0,
        }
        return [{"key": key, "count": counts.get(key, -1)} for key in SIDE_PANELS.get(place, ())]

    # Profile of the selected batch

    @Property(str, notify=batch_changed)
    def profile(self) -> str:
        if self._key is None:
            return self.batches.last_used.get(Media.EPISODES, DEFAULT_PROFILE_NAME)
        return self.batches.copy(self._key).name

    @Property(bool, notify=batch_changed)
    def profile_edited(self) -> bool:
        return self._key is not None and self.batches.copy(self._key).changed

    @Property(list, notify=batch_changed)
    def profiles(self) -> list[str]:
        return self._store.names()

    @Slot(str)
    def switch_profile(self, name: str) -> None:
        """Start the selected batch from another profile. An edited batch is discarded first, from the menu."""
        if self._key is None or self.batches.copy(self._key).changed or name == self.profile:
            return
        self.batches.switch(self._key, name)
        self.batch_changed.emit()

    @Slot()
    def discard_profile(self) -> None:
        if self._key is not None:
            self.batches.copy(self._key).revert()
            self.batch_changed.emit()

    # Programs

    @Slot()
    def refresh_programs(self) -> None:
        job = BackgroundJob(self._check)
        job.finished.connect(lambda statuses: self._on_statuses(job, statuses))
        job.failed.connect(lambda error: self._on_statuses(job, {}, error))
        self._jobs.add(job)
        job.start()

    def _on_statuses(self, job: BackgroundJob, statuses: Statuses, error: Exception | None = None) -> None:
        self._jobs.discard(job)
        if error is not None:
            _log.error("Checking the programs failed: %s", error)
        self._statuses = statuses
        self.programs_changed.emit()

    @Property(list, notify=programs_changed)
    def programs(self) -> list[dict[str, Any]]:
        rows = []
        for spec_id in SHOWN_PROGRAMS:
            name = tr(SPEC_BY_ID[spec_id].name_key)
            status = self._statuses.get(spec_id) if self._statuses is not None else None
            state = "checking" if self._statuses is None else (status.state.value if status else State.MISSING.value)
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

    @Slot(str)
    def get_program(self, spec_id: str) -> None:
        self._get_program(spec_id)
        self.refresh_programs()

    # Recent folders

    @Property(list, notify=recent_changed)
    def recent(self) -> list[dict[str, str]]:
        now = self._clock()
        return [
            {"path": folder, "name": Path(folder).name or folder, "when": when(opened, now)}
            for folder, opened in self._recent.items()
            if Path(folder).is_dir()
        ]

    # Panel sizes

    @Slot(str, result=QByteArray)
    def panel_state(self, name: str) -> QByteArray:
        saved = load_settings().value.panel_sizes.get(name, "")
        try:
            return QByteArray(base64.b64decode(saved, validate=True))
        except (binascii.Error, ValueError):
            return QByteArray()

    @Slot(str, QByteArray)
    def save_panel_state(self, name: str, state: QByteArray) -> None:
        settings = load_settings().value
        sizes = {**settings.panel_sizes, name: base64.b64encode(bytes(state.data())).decode("ascii")}
        if sizes == settings.panel_sizes:
            return
        try:
            save_settings(replace(settings, panel_sizes=sizes))
        except OSError:
            _log.exception("Could not save the panel sizes")
