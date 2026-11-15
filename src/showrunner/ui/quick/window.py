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

from PySide6.QtCore import Property, QByteArray, QModelIndex, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from showrunner.app.batches.batch import Batches, BatchKey, BatchKind, Media
from showrunner.app.batches.choices import (
    NO_CHOICE,
    TrackChoice,
    add_paired,
    choice_of,
    choose,
    move_rule,
    pause_rule,
)
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.dependencies.service import check, mkvpropedit_from, programs_from
from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.jobs.counts import count_changes
from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import FileOutcome, Preview, preview
from showrunner.app.jobs.stages import pipeline
from showrunner.app.library.library import LibraryLoad
from showrunner.app.library.loader import BackgroundJob, LibraryLoader
from showrunner.app.profiles.errors import ProfileError, ProfileExistsError
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.app.settings.app_settings import Startup, load_settings, save_settings, with_recent
from showrunner.core.media import MediaItem
from showrunner.stages.scan.extensions import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS
from showrunner.stages.tracks import TracksOptions, Verdict
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.dependencies.specs import SPEC_BY_ID
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.library.model import Kind, LibraryModel
from showrunner.ui.quick.facts import heading, video_summary, when
from showrunner.ui.quick.library import LibraryTree
from showrunner.ui.quick.plans import LivePlanner
from showrunner.ui.quick.programs_dialog import run_programs_dialog
from showrunner.ui.quick.tracks import BatchView, Column

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
# A choice is written to the workspace file this long after the last one, so a burst of clicks writes once.
SAVE_DELAY_MS = 400
# The tree dot of a file whose plan needs a decision, and of one with planned changes.
_LOOK_DOT, _PLANNED_DOT = "accent_ink", "control"
_LOOK = (FileOutcome.REFUSED, FileOutcome.NEEDS_REMUX, FileOutcome.UNWRITTEN)

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
    plans_changed = Signal()  # the live plan or the choices of the selected batch changed
    planning_changed = Signal()

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
        self._planner = LivePlanner(self)
        self._planner.planned.connect(self._on_planned)
        self._planner.busy_changed.connect(self.planning_changed)
        self._preview: Preview | None = None  # the live plan of the selected batch, once it arrived
        self._view: BatchView | None = None
        self._shown: dict[str, Any] = {}  # what QML reads about the batch, built once per plan or choice
        self._marks: dict[Path, str] = {}  # tree dots from the live plans of every batch opened
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_batches)
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
        except OSError:
            _log.exception("Could not save the workspace")
        self._save_batches()

    def _save_batches(self) -> None:
        """Write every batch's working copy at once (the file is replaced whole), so a crash loses no choice."""
        self._save_timer.stop()
        try:
            save_batches(self.batches)
        except OSError:
            _log.exception("Could not save the workspace state")

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
        self._replan()
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

    @Property(int, notify=plans_changed)
    def change_count(self) -> int:
        return sum(self._shown.get("counts", {}).values())

    @Property(str, notify=plans_changed)
    def change_text(self) -> str:
        """The top bar's "68 changes in 10 files", or "Nothing to change yet"."""
        changes, files = self.change_count, self._shown.get("files", 0)
        if not changes:
            return tr("top.nothing")
        return tr("top.changes_in", changes=tr_plural("top.changes", changes), files=tr_plural("top.files", files))

    @Property(list, notify=plans_changed)
    def workspace_tabs(self) -> list[dict[str, Any]]:
        counts = self._shown.get("counts", {})
        per_place = {
            "tracks": counts.get(ChangeGroup.TRACKS, 0),
            "names": counts.get(ChangeGroup.NAMES, 0),
            "review": sum(counts.values()),
        }
        return [
            {"key": key, "icon": icon, "count": per_place.get(key, 0), "later": later}
            for key, icon, later in WORKSPACE_TABS
        ]

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

    @Property(bool, notify=batch_changed)
    def profile_read_only(self) -> bool:
        """The built-in profile cannot be saved over; its edits go to a new profile through Save as."""
        return self._key is not None and self.batches.copy(self._key).read_only

    @Slot(str)
    def switch_profile(self, name: str) -> None:
        """Start the selected batch from another profile. An edited batch is discarded first, from the menu."""
        if self._key is None or self.batches.copy(self._key).changed or name == self.profile:
            return
        self.batches.switch(self._key, name)
        self._copy_changed()

    @Slot()
    def discard_profile(self) -> None:
        if self._key is not None:
            self.batches.copy(self._key).revert()
            self._copy_changed()

    @Slot()
    def save_profile(self) -> None:
        """Write the batch's choices to its profile, so the next batch that starts from it has them too."""
        if self._key is None or self.profile_read_only:
            return
        try:
            self.batches.copy(self._key).save()
        except (OSError, ProfileError):
            _log.exception("Could not save the profile")
        self._copy_changed()

    @Slot(str, result=str)
    def save_profile_as(self, name: str) -> str:
        """Write the choices to a new profile, which the batch then follows; returns why not, or "" when saved."""
        if self._key is None:
            return ""
        try:
            self.batches.save_as(self._key, name.strip())
        except ProfileExistsError:
            return tr("profile.error.exists", name=name.strip())
        except ProfileError:
            return tr("profile.error.name")
        except OSError as error:
            _log.exception("Could not save the profile")
            return str(error)
        self._copy_changed()
        return ""

    def _copy_changed(self) -> None:
        """Every edit of a working copy ends here: the views follow at once, a new plan starts, the file is saved."""
        self._replan()
        self._save_timer.start()
        self.batch_changed.emit()

    # Track choices of the selected batch (Overview and Tracks)

    def _tracks(self) -> TracksOptions:
        assert self._key is not None
        return self.batches.profile(self._key).for_stage("tracks")

    def _set_tracks(self, options: TracksOptions) -> None:
        assert self._key is not None
        self.batches.copy(self._key).set_options("tracks", options)
        self._copy_changed()

    def _column(self, column: int) -> tuple[Column, dict[str, Any]] | None:
        if self._view is None or not 0 <= column < len(self._view.cols):
            return None
        return self._view.cols[column], self._shown["headers"][column]

    @Slot(int)
    def toggle_keep(self, column: int) -> None:
        """A click on a chip or a column's state: drop what stays, keep what is dropped, add a paired file."""
        found = self._column(column)
        if found is None:
            return
        col, header = found
        options = self._tracks()
        if col.paired is not None:
            added = header["state"] == "added"
            if added:
                options = choose(options, col.signature, NO_CHOICE)
            self._set_tracks(add_paired(options, col.paired, not added))
            return
        choice = choice_of(options, col.signature)
        if header["state"] == "dropped":
            # Undoing a drop of this choice gives the track back; a hand-written rule that drops it takes a keep.
            verdict = Verdict.PASS if choice.verdict is Verdict.DROP else Verdict.KEEP
        else:
            verdict = Verdict.DROP
        self._set_tracks(choose(options, col.signature, TrackChoice(verdict, choice.default, choice.forced)))

    @Slot(int, str)
    def toggle_flag(self, column: int, flag: str) -> None:
        """The star (default) or F (forced) of a chip, card or column; a flag on a paired file adds the file."""
        found = self._column(column)
        if found is None or flag not in ("default", "forced"):
            return
        col, header = found
        options = self._tracks()
        choice = choice_of(options, col.signature)
        on = not getattr(choice, flag)
        flags = {"default": choice.default, "forced": choice.forced, flag: on}
        if on:
            verdict = Verdict.KEEP
        elif choice.verdict is Verdict.KEEP and not any(flags.values()):
            verdict = Verdict.PASS  # a keep that only carried the flag goes with it
        else:
            verdict = choice.verdict
        if col.paired is not None and header["state"] != "added":
            options = add_paired(options, col.paired, True)
        self._set_tracks(choose(options, col.signature, TrackChoice(verdict, **flags)))

    @Slot(int)
    def restore(self, column: int) -> None:
        """Undo every choice on a column: its rule goes, a paired file is no longer added."""
        found = self._column(column)
        if found is None:
            return
        col, _header = found
        options = choose(self._tracks(), col.signature, NO_CHOICE)
        self._set_tracks(add_paired(options, col.paired, False) if col.paired is not None else options)

    @Slot(int, int)
    def move_rule(self, source: int, target: int) -> None:
        if self._key is not None and 0 <= source < len(self._tracks().rules) and source != target:
            self._set_tracks(move_rule(self._tracks(), source, target))

    @Slot(int, bool)
    def pause_rule(self, index: int, paused: bool) -> None:
        if self._key is not None and 0 <= index < len(self._tracks().rules):
            self._set_tracks(pause_rule(self._tracks(), index, paused))

    @Slot(str)
    def focus_file(self, path: str) -> None:
        """Show one file of the batch in the Inspector. Inside a season the tree selects the episode too, which opens
        the same batch; in a show or a selection selecting it would open its season instead, so only the focus moves.
        """
        item = next((i for i in self._items if str(i.file.path) == path), None)
        if item is None:
            return
        index = self.tree.index_of(path)
        if index.isValid() and BatchKey.of(item) == self._key:
            self.select(index)
            return
        self._focus = item
        self._refresh()

    @Property(str, notify=plans_changed)
    def focus_path(self) -> str:
        return str(self._focus.file.path) if self._focus is not None else ""

    @Property(bool, notify=planning_changed)
    def planning(self) -> bool:
        return self._planner.busy

    @Property("QVariantMap", notify=plans_changed)
    def overview(self) -> dict[str, Any]:
        """Chips by kind and one row per file, for a season, a show or a selection."""
        return {"groups": self._shown.get("groups", []), "rows": self._shown.get("rows", [])}

    @Property("QVariantMap", notify=plans_changed)
    def matrix(self) -> dict[str, Any]:
        return {"headers": self._shown.get("headers", []), "rows": self._shown.get("rows", [])}

    @Property("QVariantMap", notify=plans_changed)
    def movie(self) -> dict[str, Any]:
        """The movie's video line and its tracks as cards by kind."""
        return self._shown.get("movie", {"video": "", "groups": []})

    @Property(list, notify=plans_changed)
    def rules(self) -> list[dict[str, Any]]:
        return self._shown.get("rules", [])

    @Property("QVariantMap", notify=plans_changed)
    def inspector(self) -> dict[str, Any]:
        return self._shown.get("inspector", {})

    # Live plans

    def _replan(self) -> None:
        """Show the choices at once, then plan the batch again in the background."""
        self._refresh()
        if self._key is None:
            return
        profile = self.batches.profile(self._key)
        statuses = self._statuses or {}
        stages = pipeline(programs_from(statuses), mkvpropedit_from(statuses))
        blocked = set(blocked_stages(profile)) & {s.id for s in stages}
        items = tuple(self._items)
        self._planner.request(
            self._plan_token(), lambda: preview(items, profile, stages, blocked=blocked, stamped=False)
        )

    def _plan_token(self) -> tuple[Any, ...]:
        """What a plan was made for; a result for another token is out of date when it arrives."""
        options = self.batches.profile(self._key).options if self._key is not None else None
        return (self._key, tuple(i.file.path for i in self._items), repr(options), repr(self._statuses))

    def _on_planned(self, token: object, result: Preview) -> None:
        if token != self._plan_token():
            return  # the batch or its choices changed while it was planned; a newer plan is on its way
        self._preview = result
        for file in result.files:
            path = file.item.file.path
            if file.outcome in _LOOK:
                self._marks[path] = _LOOK_DOT
            elif file.outcome is FileOutcome.CHANGES:
                self._marks[path] = _PLANNED_DOT
            else:
                self._marks.pop(path, None)
        self.model.set_plan_marks(self._marks)
        self._refresh()

    def _refresh(self) -> None:
        """Build what QML reads about the batch from its items, its choices and the live plan if it is current."""
        if self._key is None:
            self._view, self._shown = None, {}
            self.plans_changed.emit()
            return
        paths = [i.file.path for i in self._items]
        current = self._preview is not None and [f.item.file.path for f in self._preview.files] == paths
        files = self._preview.files if current and self._preview is not None else ()
        profile = self.batches.profile(self._key)
        view = BatchView.build(self._items, profile.for_stage("tracks"), files)
        focus = self._focus or (self._items[0] if self._items else None)
        counts = dict.fromkeys(ChangeGroup, 0)
        changed = 0
        for file in files:
            per_file = count_changes(file)
            changed += any(per_file.values())
            for group, count in per_file.items():
                counts[group] += count
        shown: dict[str, Any] = {
            "headers": view.headers(),
            "groups": view.groups(),
            "rows": view.rows(),
            "rules": view.rules(),
            "counts": counts,
            "files": changed,
            "inspector": view.inspector(focus, profile.for_stage("mux").original) if focus is not None else {},
        }
        if self._key.kind is BatchKind.MOVIE and self._items:
            shown["movie"] = {"video": video_summary(self._items[0]), "groups": view.card_groups(self._items[0])}
        self._view, self._shown = view, shown
        self.plans_changed.emit()

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
        self._replan()  # which stages plan depends on the programs found

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
