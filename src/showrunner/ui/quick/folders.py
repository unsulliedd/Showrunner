"""The folders open in the library: reading them and reading them again, the filter, Home, Recent, Close folder
and Remove from list.

Nothing here touches the disk beyond reading: closing a folder or taking a place out of the list only changes what the
library lists, and the folders stay in Recent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWidgets import QFileDialog

from showrunner.app.batches.batch import BatchKey, Media
from showrunner.app.library.library import Library, LibraryLoad
from showrunner.app.library.loader import LibraryLoader
from showrunner.app.settings.app_settings import Startup, load_settings, save_settings, with_recent
from showrunner.app.storage.paths import read_cache_path
from showrunner.core.media import MediaItem
from showrunner.stages.scan.extensions import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.quick.facts import when
from showrunner.ui.quick.run import Run
from showrunner.ui.quick.workspace import Workspace

_log = logging.getLogger(__name__)


def _loose(key: BatchKey) -> BatchKey:
    """A place as the library groups it: shows by title without case, whatever year each file names."""
    return replace(key, title=key.title.casefold(), year=None) if key.media is Media.EPISODES else key


def local_paths(urls: list[Any]) -> list[Path]:
    """The local files and folders among dropped or chosen URLs."""
    found = (QUrl(url) if isinstance(url, str) else url for url in urls)
    return [Path(url.toLocalFile()) for url in found if isinstance(url, QUrl) and url.isLocalFile()]


class Folders(QObject):
    filter_changed = Signal()
    recent_changed = Signal()
    home_changed = Signal()  # Home was asked for or left

    def __init__(
        self,
        workspace: Workspace,
        run: Run,
        *,
        loader: LibraryLoader | None = None,
        clock: Callable[[], datetime] = datetime.now,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._run = run
        self._clock = clock
        self._loader = loader or LibraryLoader(cache=read_cache_path(), parent=self)
        self._loader.scanned.connect(self._on_scanned)
        self._loader.file_read.connect(self._on_file_read)
        self._loader.progress.connect(self._on_progress)
        self._loader.finished.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._progress: tuple[int, int] | None = None
        self._cancelling = False
        self._refreshing: tuple[Path, ...] | None = None  # what the running load reads again, if it is a refresh
        self._unread: dict[Path, BatchKey] = {}  # the running load's videos not yet read, by their (loose) place
        self._open_unread = 0  # how many of them lie in the open place
        self._message = ""  # what the last load ended with, when it is worth saying
        self._filter = ""
        self._at_home = False  # Home is shown over an open library, which stays as it is
        self._needs_look_only = False
        settings = load_settings().value
        self._recent = dict(settings.recent_folders)
        workspace.restore = settings.last_selection
        workspace.row_selected.connect(self._count_open_unread)

    # Start and end

    def restore_workspace(self) -> None:
        settings = load_settings().value
        if settings.startup is not Startup.LAST_WORKSPACE:
            return
        self.add_paths([Path(f) for f in settings.last_folders if Path(f).is_dir()], restoring=True)

    def save_workspace(self) -> None:
        """Keep what is open for the next start: the folders, the selection and each batch's working copy."""
        workspace = self._workspace
        library = workspace.model.library
        saved = load_settings().value
        folders = [str(r) for r in library.roots] if library.items else saved.last_folders
        # The row, not the focused video: a season reopens as the season, not as its first episode alone.
        focus = workspace.selected or saved.last_selection
        try:
            save_settings(replace(saved, last_folders=folders, last_selection=focus, recent_folders=self._recent))
        except OSError:
            _log.exception("Could not save the workspace")
        if workspace.key is not None:
            workspace.batches.normalize(workspace.key.root)
        workspace.save_batches()

    # Library

    @property
    def loaded(self) -> bool:
        return bool(self._workspace.model.library.items)

    @property
    def needs_look(self) -> int:
        return self._workspace.model.needs_look_count()

    @property
    def busy(self) -> bool:
        return self._loader.busy

    @property
    def read_fraction(self) -> float:
        """How much of the load's reading is done, from 0 to 1; 0 while the folders are scanned."""
        if self._progress is None or not self._progress[1]:
            return 0.0
        done, total = self._progress
        return done / total

    @property
    def job_text(self) -> str:
        if self._cancelling:
            return tr("status.cancelling")
        if self._progress is not None:
            done, total = self._progress
            return tr("status.reading", done=done, total=total)
        if self._loader.busy:
            return tr("status.scanning")
        return self._message or tr("statusbar.no_jobs")

    @property
    def reading_open_batch(self) -> bool:
        """Whether files of the open place are still being read, so the workspace waits. With nothing open yet (the
        start, or after Close folder) the place that will open comes out of this load, so it waits as well."""
        if not self._loader.busy or self._cancelling:
            return False
        return self._workspace.key is None or self._open_unread > 0

    def _count_open_unread(self) -> None:
        open_key = self._workspace.key
        place = _loose(open_key) if open_key is not None else None
        self._open_unread = sum(1 for key in self._unread.values() if place is not None and key.within(place))
        if self._loader.busy:
            self._workspace.loading_changed.emit()

    @property
    def filter_text(self) -> str:
        return self._filter

    @filter_text.setter
    def filter_text(self, text: str) -> None:
        if text != self._filter:
            self._filter = text
            self._workspace.tree.set_text(text)
            self.filter_changed.emit()

    @property
    def needs_look_only(self) -> bool:
        return self._needs_look_only

    @needs_look_only.setter
    def needs_look_only(self, enabled: bool) -> None:
        if enabled != self._needs_look_only:
            self._needs_look_only = enabled
            self._workspace.tree.set_needs_look(enabled)
            self.filter_changed.emit()

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, tr("home.choose_folder"))
        if folder:
            self.add_paths([Path(folder)])

    def choose_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS | SUBTITLE_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(None, tr("home.choose_files"), "", f"{tr('home.files')} ({patterns})")
        self.add_paths([Path(f) for f in files])

    def add_urls(self, urls: list[Any]) -> None:
        self.add_paths(local_paths(urls))

    def open_recent(self, folder: str) -> None:
        self.add_paths([Path(folder)])

    def close_folder(self) -> None:
        """Back to Home: the library is emptied and nothing stays selected, and the next start opens on Home as well.
        Nothing on disk changes; the folders stay in Recent and each batch keeps its saved choices. What was taken out
        of the list is forgotten with the library, since adding a folder again lists all of it."""
        if not self.can_change_library:
            return
        self._workspace.batches.removed.clear()
        self._clear_view(Library())
        self._remember(last_folders=[], last_selection="")
        self._workspace.save_soon()

    @property
    def can_change_library(self) -> bool:
        """Videos are taken out of the library, or all folders closed, only while it is open and no file of it is
        read, applied or read again."""
        return self.loaded and not self._loader.busy and not self._run.applying and not self._run.locked_paths()

    def _clear_view(self, library: Library) -> None:
        """Show `library`, which holds no videos, with nothing selected: Home."""
        self.filter_text = ""
        self.needs_look_only = False
        self._message = ""
        self._at_home = False
        self._workspace.clear(library)

    def _show_library(self, library: Library, gone: set[Path], above: list[str] | None = None) -> None:
        """Show `library`, the open one without the videos at `gone`; the selection stays where its row does, else
        moves to the nearest of the rows `above` it that is left."""
        if not library.items:
            self._clear_view(library)
            return
        workspace = self._workspace
        for path in gone:
            workspace.marks.pop(path, None)
        workspace.model.set_library(library)
        workspace.restore = next((row for row in above or [] if workspace.tree.index_of(row).isValid()), "")
        workspace.reselect()
        workspace.loading_changed.emit()

    def _above(self) -> list[str]:
        """The rows above the selected one, nearest first."""
        tree = self._workspace.tree
        above, index = [], tree.index_of(self._workspace.selected).parent()
        while index.isValid():
            above.append(tree.row_id(index))
            index = index.parent()
        return above

    # Home

    @property
    def home_shown(self) -> bool:
        """Home is what the window shows: nothing is open, or Home was asked for over an open library."""
        return not self.loaded or self._at_home

    def go_home(self) -> None:
        """Show Home without closing anything: the open folders, the selection and every choice stay as they are, and
        a click on a row of the library, or on Back to the library, shows the workspace again."""
        if self.loaded and not self._at_home:
            self._at_home = True
            self.home_changed.emit()

    def leave_home(self) -> None:
        if self._at_home:
            self._at_home = False
            self.home_changed.emit()

    # Remove from list and Close folder, from the library's menu

    def remove_place(self) -> None:
        """Take the selected place's videos out of the library's list and remember it with the workspace. They stay out
        when the app is opened again, until their folder is added again; nothing on disk changes. Unlike Exclude, the
        place is no longer listed, and its choices and exclusion are kept for when it comes back."""
        workspace = self._workspace
        if workspace.key is None or not self.can_change_library:
            return
        gone = {i.file.path for i in workspace.items}
        workspace.batches.removed |= gone
        self._show_library(workspace.model.library.without(gone), gone, self._above())
        workspace.save_soon()

    def folders_of_place(self) -> tuple[Path, ...]:
        """The opened folders the selected show or Movies group lists videos from; none for a place inside a show and
        for videos that were opened one by one."""
        workspace = self._workspace
        if workspace.key is None or workspace.key.parent is not None:
            return ()
        return workspace.model.library.folders_of(i.file.path for i in workspace.items)

    def close_place_folders(self) -> None:
        """Close the folders the selected show or Movies group comes from, with everything listed from them. The other
        open folders stay; a folder that holds several shows takes them all."""
        folders = self.folders_of_place()
        if not folders or not self.can_change_library:
            return
        batches, library = self._workspace.batches, self._workspace.model.library
        gone = {i.file.path for i in library.items if any(i.file.path.is_relative_to(f) for f in folders)}
        batches.removed = {p for p in batches.removed if not any(p.is_relative_to(f) for f in folders)}
        closed = library.closed(folders)
        self._show_library(closed, gone)
        self._remember(last_folders=[str(r) for r in closed.roots])
        self._workspace.save_soon()

    # Recent folders

    @property
    def recent(self) -> list[dict[str, str]]:
        now = self._clock()
        return [
            {"path": folder, "name": Path(folder).name or folder, "when": when(opened, now)}
            for folder, opened in self._recent.items()
            if Path(folder).is_dir()
        ]

    def recent_actions(self) -> list[dict[str, Any]]:
        """The right-click menu of a recent folder."""
        return [
            {"key": "open", "text": tr("home.recent.open"), "enabled": True},
            {"key": "remove", "text": tr("home.recent.remove"), "enabled": True},
        ]

    def remove_recent(self, folder: str) -> None:
        """Take a folder off the Recent list; the folder itself is not touched."""
        if folder in self._recent:
            self._recent = {f: opened for f, opened in self._recent.items() if f != folder}
            self.recent_changed.emit()
            self._remember()

    def _remember(self, **changes: Any) -> None:
        """Write the recent folders, with `changes` to other settings, at once rather than at exit."""
        try:
            save_settings(replace(load_settings().value, recent_folders=self._recent, **changes))
        except OSError:
            _log.exception("Could not save the workspace")

    # Reading

    def add_paths(self, paths: list[Path], *, restoring: bool = False) -> None:
        """Read `paths` and add what was found. Adding a folder or a file again lists the videos of it that were taken
        out of the list; the folders opened again at the start (`restoring`) leave them out."""
        # A second drop while reading is ignored: the loader runs one load at a time.
        if not paths or self._loader.busy:
            return
        self._message = ""
        batches = self._workspace.batches
        known = [item.file.path for item in self._workspace.model.library.items]
        if restoring:
            known += batches.removed
        elif batches.removed:
            batches.removed = {p for p in batches.removed if not any(p.is_relative_to(a) for a in paths)}
            self._workspace.save_soon()
        self._loader.start(paths, known=known)
        self._workspace.loading_changed.emit()

    def sources(self, paths: Iterable[Path]) -> tuple[Path, ...]:
        """What to read again for the videos at `paths`: the opened folders that hold them, and those opened one by
        one. A place inside a show reads its whole folder again, since a scan of a subfolder alone would list it as a
        folder of its own."""
        library = self._workspace.model.library
        paths = tuple(paths)
        return (*library.folders_of(paths), *(p for p in paths if not library.folders_of((p,))))

    def refresh(self, paths: Iterable[Path] | None = None) -> None:
        """Read `paths`, or every open folder and file, again: files deleted on disk drop out, new ones come in, and
        only files that changed are read, the others served from the read cache. Choices, kept per place, stay."""
        if not self.can_change_library:
            return
        library = self._workspace.model.library
        if paths is None:
            paths = self.sources(i.file.path for i in library.items)
            paths = (*library.roots, *(p for p in paths if p not in library.roots))
        paths = tuple(paths)
        present = [p for p in paths if p.exists()]
        self._message = ""
        if not present:
            self._renew(paths, LibraryLoad())
            return
        self._refreshing = paths
        # What was taken out of the list stays out, as when the folders are opened again at the start.
        self._loader.start(present, known=self._workspace.batches.removed)
        self._workspace.loading_changed.emit()

    def refresh_place(self) -> None:
        """Read the folders the selected place comes from again."""
        if self._workspace.key is not None:
            self.refresh(self.sources(i.file.path for i in self._workspace.items))

    def _renew(self, paths: tuple[Path, ...], load: LibraryLoad) -> None:
        library = self._workspace.model.library
        renewed = library.renewed(paths, load)
        gone = {i.file.path for i in library.items} - {i.file.path for i in renewed.items}
        self._show_library(renewed, gone, self._above())
        if renewed.roots != library.roots:
            self._remember(last_folders=[str(r) for r in renewed.roots])

    def cancel_reading(self) -> None:
        """Stop the load after the file being read; what was read so far is kept and the rest shows as not read."""
        if self._loader.busy:
            self._loader.cancel()
            self._cancelling = True
            self._workspace.loading_changed.emit()

    def _on_scanned(self, items: tuple[MediaItem, ...]) -> None:
        self._unread = {item.file.path: _loose(BatchKey.file(item)) for item in items}
        self._count_open_unread()

    def _on_file_read(self, path: Path) -> None:
        key = self._unread.pop(path, None)
        if key is not None and self._workspace.key is not None and key.within(_loose(self._workspace.key)):
            self._open_unread -= 1

    def _on_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)
        self._workspace.loading_changed.emit()

    def _on_failed(self, error: Exception) -> None:
        _log.error("Loading failed: %s", error)
        self._progress = None
        self._refreshing = None
        self._unread, self._open_unread = {}, 0
        self._cancelling = False
        self._message = tr("status.load_failed", error=error)
        self._workspace.loading_changed.emit()

    def _on_loaded(self, load: LibraryLoad) -> None:
        self._progress = None
        self._unread, self._open_unread = {}, 0
        self._cancelling = False
        refreshing, self._refreshing = self._refreshing, None
        if refreshing is not None:
            # A cancelled refresh leaves the library as it was: its load holds files it did not reach as not read.
            if load.cancelled:
                self._message = tr("status.refresh_cancelled")
                self._workspace.loading_changed.emit()
            elif self._run.applying or self._run.locked_paths():
                # A job started meanwhile: its files must not be replaced under it, nor dropped from the list.
                self._message = tr("status.refresh_skipped")
                self._workspace.loading_changed.emit()
            else:
                self._renew(refreshing, load)
            return
        if load.cancelled:
            self._message = tr("status.cancelled")
        else:
            self._message = "" if load.items else tr("status.nothing_new")
        self._workspace.model.add(load)
        if load.roots:
            self._recent = with_recent(self._recent, [str(root) for root in load.roots], self._clock())
            self.recent_changed.emit()
        self._at_home = False  # what was just opened is what the user looks at
        self.home_changed.emit()
        self._workspace.reselect()
        self._workspace.loading_changed.emit()
