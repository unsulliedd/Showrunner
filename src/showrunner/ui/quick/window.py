"""The controller behind the Qt Quick window: the library, the selected batch, the programs and the workspace state.

QML reads its properties and calls its slots; it holds no logic of its own. Loading, checking programs and saving
go through the app layer, and slow work runs on pool threads through `BackgroundJob`.

Apply never runs from a live plan: it plans the batch again with stamps on a pool thread, refuses to start when a
file changed since it was read, stores the job and hands it to `Jobs`, which runs it on a pool thread too. The batch is
locked from the press until the job ends.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QByteArray, QModelIndex, QObject, QThreadPool, QTimer, QUrl, Signal, Slot
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
from showrunner.app.batches.leave_out import LeftOut
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.dependencies.service import check, mkvpropedit_from, probe_file, programs_from
from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.jobs.counts import count_changes
from showrunner.app.jobs.groups import TITLE_TEMPLATE, ChangeGroup
from showrunner.app.jobs.preview import FileOutcome, FilePreview, Preview, preview
from showrunner.app.jobs.run import JobResult, Read, StalePreviewError, create_job
from showrunner.app.jobs.stages import Stage, pipeline
from showrunner.app.jobs.store import JobStore, StepState
from showrunner.app.library.library import LibraryLoad
from showrunner.app.library.loader import BackgroundJob, LibraryLoader
from showrunner.app.profiles.errors import ProfileError, ProfileExistsError
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.app.settings.app_settings import Startup, load_settings, save_settings, with_recent
from showrunner.app.storage.paths import jobs_path, read_cache_path
from showrunner.core.media import MediaFile, MediaItem
from showrunner.core.naming import (
    SUGGESTED_TEMPLATES,
    TOKENS,
    CustomKind,
    CustomToken,
    NamingOptions,
    PatternSource,
    parse,
    pieces,
)
from showrunner.stages.mux import MuxResult, Original
from showrunner.stages.scan.extensions import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS
from showrunner.stages.tracks import TracksOptions, Verdict
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.dependencies.specs import SPEC_BY_ID
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.library.model import Kind, LibraryModel
from showrunner.ui.quick import names as rail
from showrunner.ui.quick.facts import heading, video_summary, when
from showrunner.ui.quick.jobs import Jobs
from showrunner.ui.quick.library import LibraryTree
from showrunner.ui.quick.palette import Entry, search
from showrunner.ui.quick.plans import LivePlanner
from showrunner.ui.quick.review import FILTERS, ReviewInput, review, totals
from showrunner.ui.quick.settings import SECTIONS, Settings
from showrunner.ui.quick.tracks import BatchView, Column, item_number, item_title

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
# The places whose data is built only while they show, with the signal that tells QML it changed.
_PLACE_SIGNALS = {"overview": "overview_changed", "tracks": "matrix_changed", "review": "review_changed"}
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
# How long closing the window waits for a cancelled job to stop its program and leave the files in a known place.
STOP_WAIT_MS = 10_000

type Statuses = dict[str, DependencyStatus]
type MakePipeline = Callable[[Statuses], Sequence[Stage]]


def default_pipeline(statuses: Statuses) -> tuple[Stage, ...]:
    return pipeline(programs_from(statuses), mkvpropedit_from(statuses))


@dataclass(frozen=True, slots=True)
class _Applying:
    """What an Apply was pressed with, kept while its stamped preview is made."""

    paths: frozenset[Path]
    profile: Any
    stages: tuple[Stage, ...]
    blocked: frozenset[str]
    groups: frozenset[ChangeGroup]
    out: frozenset[Path]
    live: dict[Path, Any]  # each file's plans in the run plan on screen
    name: str  # the batch, as the job names it


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
    names_changed = Signal()  # what the Names place or the Tokens panel shows changed
    # What one place shows changed; each is emitted only while its place shows, and on switching to it.
    overview_changed = Signal()
    matrix_changed = Signal()
    review_changed = Signal()
    apply_changed = Signal()  # whether Apply can start, or why it did not
    palette_changed = Signal()
    palette_asked = Signal(str, str)  # the palette asks the window for a place ("place", key) or the drawer

    def __init__(
        self,
        *,
        statuses: Callable[[], Statuses] = check_shown,
        loader: LibraryLoader | None = None,
        store: ProfileStore | None = None,
        get_program: Callable[[str], None] | None = None,
        clock: Callable[[], datetime] = datetime.now,
        jobs: JobStore | None = None,
        make_pipeline: MakePipeline = default_pipeline,
        read: Read | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = LibraryModel(self)
        self.tree = LibraryTree(self)
        self.tree.setSourceModel(self.model)
        self._loader = loader or LibraryLoader(cache=read_cache_path(), parent=self)
        self._loader.progress.connect(self._on_progress)
        self._loader.finished.connect(self._on_loaded)
        self._loader.failed.connect(self._on_failed)
        self._check = statuses
        self._clock = clock
        self._store = store or ProfileStore()
        self.batches: Batches = load_batches(self._store)
        self._statuses: Statuses | None = None
        self._jobs: set[BackgroundJob] = set()
        self._progress: tuple[int, int] | None = None
        self._cancelling = False
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
        self._planner.busy_changed.connect(self.apply_changed)
        self._preview: Preview | None = None  # the live plan of the selected batch, once it arrived
        self._run_preview: Preview | None = None  # the same with the left-out groups emptied, as Apply runs it
        self.left_out = LeftOut()
        self._review_filter = "all"
        self._make_pipeline = make_pipeline
        self._read_file = read
        self._applying: _Applying | None = None  # an Apply whose stamped preview is being made
        self._apply_message = ""
        self._offered = False  # unfinished jobs are offered once, when the programs are first known
        self._job_view = Jobs(jobs or JobStore(jobs_path()), self._job_pipeline, self._names_of, parent=self)
        self._job_view.started.connect(self._on_lock_changed)
        self._job_view.ended.connect(self._on_job_ended)
        self._view: BatchView | None = None
        self._shown: dict[str, Any] = {}  # what QML reads about the batch, built once per plan or choice
        # The parts of `_shown` a single place shows, built on first read after a plan or choice.
        self._built: dict[str, Any] = {}
        self._place = "overview"  # the workspace place the window shows
        self._stale: set[str] = set()  # places whose change was not signalled while they were hidden
        self._template = TITLE_TEMPLATE  # the template the Names builder shows
        self._token_query = ""
        self._palette_query = ""
        self._editing = -1  # the custom token open in the Tokens panel's editor
        self._editing_builtin = ""  # or the built-in token open there, for its value map
        self._names: dict[str, Any] | None = {}  # what the Names place and the Tokens panel read; None until read
        self._marks: dict[Path, str] = {}  # tree dots from the live plans of every batch opened
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_batches)
        self._settings = Settings(self)
        self.look = self._settings.look
        self._settings.programs_view.statuses_changed.connect(self.refresh_programs)
        self._get_program = get_program or self._settings.get_program
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

    def stop_jobs(self) -> None:
        """Cancel a running job as the window closes and wait for its program to stop. The mux stage removes its
        partial file and leaves the original untouched; the job is offered to resume at the next start."""
        if self.jobs.busy:
            self.jobs.cancel()
            QThreadPool.globalInstance().waitForDone(STOP_WAIT_MS)

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

    @Property(float, notify=loading_changed)
    def read_fraction(self) -> float:
        """How much of the load's reading is done, from 0 to 1; 0 while the folders are scanned."""
        if self._progress is None or not self._progress[1]:
            return 0.0
        done, total = self._progress
        return done / total

    @Property(str, notify=loading_changed)
    def job_text(self) -> str:
        if self._cancelling:
            return tr("status.cancelling")
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

    @Slot()
    def cancel_reading(self) -> None:
        """Stop the load after the file being read; what was read so far is kept and the rest shows as not read."""
        if self._loader.busy:
            self._loader.cancel()
            self._cancelling = True
            self.loading_changed.emit()

    def _on_progress(self, done: int, total: int) -> None:
        self._progress = (done, total)
        self.loading_changed.emit()

    def _on_failed(self, error: Exception) -> None:
        _log.error("Loading failed: %s", error)
        self._progress = None
        self._cancelling = False
        self._message = tr("status.load_failed", error=error)
        self.loading_changed.emit()

    def _on_loaded(self, load: LibraryLoad) -> None:
        self._progress = None
        self._cancelling = False
        if load.cancelled:
            self._message = tr("status.cancelled")
        else:
            self._message = "" if load.items else tr("status.nothing_new")
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
        previous = self._key
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
        if self._key != previous:
            self._editing = -1  # the open token belongs to the other batch's profile
            self._editing_builtin = ""
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
        """What Apply would write: the run plan's changes, without left-out groups and files."""
        return int(self._shown.get("totals", (0, 0))[0])

    @Property(str, notify=plans_changed)
    def change_text(self) -> str:
        """The top bar's "68 changes in 10 files", or "Nothing to change yet"."""
        changes, files = self._shown.get("totals", (0, 0))
        if not changes:
            return tr("top.nothing")
        return tr("top.changes_in", changes=tr_plural("top.changes", changes), files=tr_plural("top.files", files))

    @Property(list, notify=plans_changed)
    def workspace_tabs(self) -> list[dict[str, Any]]:
        counts = self._shown.get("counts", {})
        per_place = {
            "tracks": counts.get(ChangeGroup.TRACKS, 0),
            "names": counts.get(ChangeGroup.NAMES, 0),
            "review": self.change_count,
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
        if self._key is None or self.locked or self.batches.copy(self._key).changed or name == self.profile:
            return
        self.batches.switch(self._key, name)
        self._copy_changed()

    @Slot()
    def discard_profile(self) -> None:
        if self._key is not None and not self.locked:
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

    @Property(QObject, constant=True)
    def settings(self) -> Settings:
        """The Settings dialog's side: General, Profiles, Programs, Appearance, Shortcuts and About."""
        return self._settings

    @property
    def store(self) -> ProfileStore:
        return self._store

    def profiles_edited(self) -> None:
        """Settings changed profile files: the selected batch plans again, and the pill and lists follow."""
        self._copy_changed()

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
        if self.locked:
            return
        self.batches.copy(self._key).set_options("tracks", options)
        self._copy_changed()

    def _column(self, column: int) -> tuple[Column, dict[str, Any]] | None:
        if self._view is None or not 0 <= column < len(self._view.cols):
            return None
        return self._view.cols[column], self._headers()[column]

    @Slot(int, result="QVariantList")
    def track_names(self, column: int) -> list[str]:
        """The ▾ list of a chip or matrix column: each file's name for its track, built when the list opens."""
        return self._view.names(column) if self._view is not None else []

    @Slot(int, result=str)
    def track_missing(self, column: int) -> str:
        """The line naming the files that lack a chip's or matrix column's track; empty when every file has it."""
        return self._view.missing(column) if self._view is not None else ""

    @Slot(int, result=str)
    def track_held(self, column: int) -> str:
        """The line naming the files that keep a dropped chip's track and why; empty when the plan drops it where it
        can."""
        return self._view.held_note(column) if self._view is not None else ""

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
        if choice.verdict is Verdict.DROP:
            # Undoing this choice's drop gives the track back, also when a refused plan shows the track kept.
            verdict = Verdict.PASS
        elif header["state"] == "dropped":
            verdict = Verdict.KEEP  # a hand-written rule drops it
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

    @Slot(int)
    def remove_rule(self, index: int) -> None:
        """Delete a hand-written rule. A rule a choice wrote goes by undoing the choice on its track instead."""
        rules = self._tracks().rules if self._key is not None else []
        if 0 <= index < len(rules) and not rules[index].from_choice:
            self._set_tracks(replace(self._tracks(), rules=rules[:index] + rules[index + 1 :]))

    @Property("QVariantMap", notify=batch_changed)
    def untagged(self) -> dict[str, str]:
        """The language given to tracks that have none, in the selected batch, and why it cannot be used."""
        if self._key is None:
            return {"value": "", "problem": ""}
        profile = self.batches.profile(self._key)
        block = blocked_stages(profile).get("metadata")
        bad = block.language if block is not None else ""
        return {
            "value": profile.for_stage("metadata").untagged_language,
            "problem": tr("names.blocked.language", language=bad) if bad else "",
        }

    @Slot(str)
    def set_untagged_language(self, text: str) -> None:
        if self._key is None or self.locked:
            return
        metadata = self.batches.profile(self._key).for_stage("metadata")
        if text.strip() != metadata.untagged_language:
            self.batches.copy(self._key).set_options("metadata", replace(metadata, untagged_language=text.strip()))
            self._copy_changed()

    @Property(bool, notify=batch_changed)
    def write_implied_flags(self) -> bool:
        """Whether a track named Forced, SDH or Commentary also gets that flag written, in the selected batch."""
        return self._key is not None and self.batches.profile(self._key).for_stage("metadata").write_implied_flags

    @Slot(bool)
    def set_write_implied_flags(self, on: bool) -> None:
        if self._key is None or self.locked or on == self.write_implied_flags:
            return
        metadata = self.batches.profile(self._key).for_stage("metadata")
        self.batches.copy(self._key).set_options("metadata", replace(metadata, write_implied_flags=on))
        self._copy_changed()

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
        # Only the Inspector and the Names result follow the focus; rows, headers and Review stay as built.
        if self._shown:
            self._shown["inspector"] = self._inspector()
        self.plans_changed.emit()
        self._refresh_names()

    @Property(str, notify=plans_changed)
    def focus_path(self) -> str:
        """The file the Inspector and Names show: the focused one, else the batch's first."""
        focus = self._focus or (self._items[0] if self._items else None)
        return str(focus.file.path) if focus is not None else ""

    @Property(bool, notify=planning_changed)
    def planning(self) -> bool:
        return self._planner.busy

    def _part(self, key: str, build: Callable[[], Any]) -> Any:
        """A part one place shows, built on its first read after a plan or choice."""
        if key not in self._built:
            self._built[key] = build()
        return self._built[key]

    def _headers(self) -> list[dict[str, Any]]:
        return self._part("headers", self._view.headers) if self._view is not None else []

    def _rows(self) -> list[dict[str, Any]]:
        return self._part("rows", self._view.rows) if self._view is not None else []

    @Property("QVariantMap", notify=overview_changed)
    def overview(self) -> dict[str, Any]:
        """Chips by kind and one row per file, for a season, a show or a selection."""
        groups = self._part("groups", self._view.groups) if self._view is not None else []
        return {"groups": groups, "rows": self._rows()}

    @Property("QVariantMap", notify=matrix_changed)
    def matrix(self) -> dict[str, Any]:
        return {"headers": self._headers(), "rows": self._rows()}

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

    # Names: the templates and the custom tokens of the selected batch

    def _naming(self) -> NamingOptions:
        assert self._key is not None
        return self.batches.profile(self._key).for_stage("naming")

    def _set_naming(self, options: NamingOptions) -> None:
        if self._key is None or self.locked or options == self._naming():
            self._refresh_names()  # a locked batch's rail shows its template again
            return
        self.batches.copy(self._key).set_options("naming", options)
        self._copy_changed()

    def _set_template(self, text: str) -> None:
        if self._key is not None:
            self._set_naming(replace(self._naming(), **{self._template: text}))

    def _template_text(self) -> str:
        return getattr(self._naming(), self._template) if self._key is not None else ""

    @Property("QVariantMap", notify=names_changed)
    def names(self) -> dict[str, Any]:
        """The template cards, the builder rail of the picked one, its result and the batch before and after."""
        return self._names_built().get("place", {})

    @Property("QVariantMap", notify=names_changed)
    def tokens(self) -> dict[str, Any]:
        return self._names_built().get("tokens", {"groups": [], "editor": {}})

    def _names_built(self) -> dict[str, Any]:
        if self._names is None:
            self._names = self._build_names()
        return self._names

    @Slot(str)
    def pick_template(self, template: str) -> None:
        if template in rail.TEMPLATES and template != self._template:
            self._template = template
            self._refresh_names()

    @Slot(str)
    def start_template(self, template: str) -> None:
        """Pick a card and fill its empty template with the suggested one."""
        if template not in rail.TEMPLATES:
            return
        self._template = template
        if self._template_text():
            self._refresh_names()
            return
        self._set_template(SUGGESTED_TEMPLATES[template])

    @Slot()
    def clear_template(self) -> None:
        self._set_template("")

    @Slot(int, str)
    def rail_insert(self, at: int, name: str) -> None:
        self._set_template(rail.insert_token(self._template_text(), at, name))

    @Slot(str)
    def rail_append(self, name: str) -> None:
        text = self._template_text()
        self._set_template(rail.insert_token(text, len(pieces(parse(text))), name))

    @Slot(int, int)
    def rail_move(self, source: int, target: int) -> None:
        self._set_template(rail.move_token(self._template_text(), source, target))

    @Slot(int)
    def rail_remove(self, at: int) -> None:
        self._set_template(rail.remove_piece(self._template_text(), at))

    @Slot(int, str)
    def rail_set_text(self, at: int, text: str) -> None:
        self._set_template(rail.set_text(self._template_text(), at, text))

    @Slot(int, str)
    def rail_add_text(self, at: int, text: str) -> None:
        self._set_template(rail.add_text(self._template_text(), at, text))

    @Slot(int)
    def rail_optional(self, at: int) -> None:
        self._set_template(rail.toggle_optional(self._template_text(), at))

    @Slot(int)
    def rail_padding(self, at: int) -> None:
        self._set_template(rail.cycle_padding(self._template_text(), at))

    def _get_token_query(self) -> str:
        return self._token_query

    def _set_token_query(self, text: str) -> None:
        if text != self._token_query:
            self._token_query = text
            self._refresh_names()

    token_query = Property(str, _get_token_query, _set_token_query, notify=names_changed)

    def _custom(self) -> list[CustomToken]:
        return list(self._naming().custom_tokens) if self._key is not None else []

    @Slot()
    def add_token(self) -> None:
        """A new text token with a free name, open in the editor."""
        if self._key is None:
            return
        custom = self._custom()
        self._editing, self._editing_builtin = len(custom), ""
        self._set_naming(replace(self._naming(), custom_tokens=[*custom, CustomToken(rail.new_token_name(custom))]))

    @Slot(int)
    def edit_token(self, index: int) -> None:
        """Open a custom token in the editor; -1 closes it."""
        self._editing = index if 0 <= index < len(self._custom()) else -1
        self._editing_builtin = ""
        self._refresh_names()

    @Slot(str)
    def edit_builtin(self, name: str) -> None:
        """Open a built-in token in the editor, for its value map; "" closes it."""
        self._editing, self._editing_builtin = -1, name if name in TOKENS else ""
        self._refresh_names()

    @Slot(str, int, str, str)
    def set_value_map(self, name: str, row: int, read: str, written: str) -> None:
        """Set one row of a token's value map: what the token reads, and what is written instead."""
        if self._key is not None and not self.locked and row >= 0:
            self._set_naming(rail.set_map_row(self._naming(), name, row, read, written))

    def _change_token(self, index: int, **changes: Any) -> None:
        custom = self._custom()
        if 0 <= index < len(custom):
            custom[index] = replace(custom[index], **changes)
            self._set_naming(replace(self._naming(), custom_tokens=custom))

    @Slot(int, str)
    def rename_token(self, index: int, name: str) -> None:
        """Rename a custom token, and its uses in the templates, other tokens and value maps with it."""
        custom = self._custom()
        if not 0 <= index < len(custom) or name == custom[index].name:
            return
        naming = rail.rename_token(self._naming(), custom[index].name, name)
        tokens = list(naming.custom_tokens)
        tokens[index] = replace(tokens[index], name=name)
        self._set_naming(replace(naming, custom_tokens=tokens))

    @Slot(int, str)
    def set_token_kind(self, index: int, kind: str) -> None:
        if kind in rail.KINDS:
            self._change_token(index, kind=CustomKind(kind))

    @Slot(int, str)
    def set_token_text(self, index: int, text: str) -> None:
        self._change_token(index, text=text)

    @Slot(int, str)
    def set_token_source(self, index: int, source: str) -> None:
        if source in rail.SOURCES:
            self._change_token(index, source=PatternSource(source))

    @Slot(int)
    def remove_token(self, index: int) -> None:
        custom = self._custom()
        if not 0 <= index < len(custom):
            return
        self._editing = -1
        name, kept = custom[index].name, custom[:index] + custom[index + 1 :]
        maps = self._naming().value_maps
        # A value map of a token that is gone would block Metadata, with nothing here to fix it.
        if all(t.name != name for t in kept):
            maps = {token: values for token, values in maps.items() if token != name}
        self._set_naming(replace(self._naming(), custom_tokens=kept, value_maps=maps))

    def _refresh_names(self) -> None:
        """Build what Names and Tokens show; QML hears of it only when it changed, so a plan that arrives while text
        is typed does not rebuild the rail under the cursor. While Names is hidden nothing is built: it is built when
        read, and QML hears of it on switching to Names."""
        if self._place != "names":
            self._names = None
            self._stale.add("names")
            return
        self._stale.discard("names")
        built = self._build_names()
        if built != self._names:
            self._names = built
            self.names_changed.emit()

    def _build_names(self) -> dict[str, Any]:
        built: dict[str, Any] = {}
        if self._key is not None:
            profile = self.batches.profile(self._key)
            given = rail.NamesInput(
                items=self._items,
                focus=self._focus,
                media=self._key.media,
                naming=profile.for_stage("naming"),
                tracks=profile.for_stage("tracks"),
                template=self._template,
                files=self._current_files(),
                block=blocked_stages(profile).get("metadata"),
                batch_title=heading(self._key, self._items).title,
            )
            built = {
                "place": rail.place(given),
                "tokens": rail.tokens(given, self._token_query, self._editing, self._editing_builtin),
            }
        return built

    def _current_files(self, plan: Preview | None = None) -> tuple[FilePreview, ...]:
        """The live plan's files when it was made for the batch's files as they are now."""
        plan = plan or self._preview
        paths = [i.file.path for i in self._items]
        if plan is None or [f.item.file.path for f in plan.files] != paths:
            return ()
        return plan.files

    # Live plans

    def _replan(self) -> None:
        """Show the choices at once, then plan the batch again in the background."""
        self._refresh()
        if self._key is None:
            return
        profile = self.batches.profile(self._key)
        statuses = self._statuses or {}
        stages = tuple(self._make_pipeline(statuses))
        blocked = set(blocked_stages(profile)) & {s.id for s in stages}
        items = tuple(self._items)
        groups = self.left_out.groups_of(self._key)

        def work() -> tuple[Preview, Preview]:
            full = preview(items, profile, stages, blocked=blocked, stamped=False)
            run = preview(items, profile, stages, blocked=blocked, left_out=groups, stamped=False) if groups else full
            return full, run

        self._planner.request(self._plan_token(), work)

    def _plan_token(self) -> tuple[Any, ...]:
        """What a plan was made for; a result for another token is out of date when it arrives."""
        if self._key is None:
            return (None,)
        options = self.batches.profile(self._key).options
        groups = sorted(self.left_out.groups_of(self._key))
        return (self._key, tuple(i.file.path for i in self._items), repr(options), repr(self._statuses), groups)

    def _on_planned(self, token: object, result: tuple[Preview, Preview]) -> None:
        if token != self._plan_token():
            return  # the batch or its choices changed while it was planned; a newer plan is on its way
        self._preview, self._run_preview = result
        for file in self._preview.files:
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
        """Build what QML reads about the batch from its items, its choices and the live plan if it is current. What
        only one place shows (rows, chips, headers, Review, Names) is built when read, and signalled only while that
        place shows, so a whole show's 300 rows are not built for places nobody looks at."""
        self._built = {}
        self._stale |= set(_PLACE_SIGNALS)
        if self._key is None:
            self._view, self._shown = None, {}
        else:
            files = self._current_files()
            profile = self.batches.profile(self._key)
            self._view = BatchView.build(self._items, profile.for_stage("tracks"), files, self._failures())
            counts = dict.fromkeys(ChangeGroup, 0)
            for file in files:
                for group, count in count_changes(file).items():
                    counts[group] += count
            self._shown = {"rules": self._view.rules(), "counts": counts, "inspector": self._inspector()}
            if self._key.kind is BatchKind.MOVIE and self._items:
                groups = self._view.card_groups(self._items[0])
                self._shown["movie"] = {"video": video_summary(self._items[0]), "groups": groups}
            self._shown["review_input"] = given = self._review_input()
            self._shown["totals"] = totals(given)
        self.plans_changed.emit()
        self.apply_changed.emit()
        self._signal_shown()
        self._refresh_names()

    def _failures(self) -> dict[str, str]:
        """Why each file of the batch whose tracks could not be read was not read."""
        library = self.model.library
        return {str(i.file.path): reason for i in self._items if (reason := library.failure(i.file.path)) is not None}

    def _inspector(self) -> dict[str, Any]:
        focus = self._focus or (self._items[0] if self._items else None)
        if self._view is None or self._key is None or focus is None:
            return {}
        return self._view.inspector(focus, self.batches.profile(self._key).for_stage("mux").original)

    def _signal_shown(self) -> None:
        signal = _PLACE_SIGNALS.get(self._place)
        if signal is not None and self._place in self._stale:
            self._stale.discard(self._place)
            getattr(self, signal).emit()

    @Slot(str)
    def show_place(self, place: str) -> None:
        """The window shows another workspace place; what changed there while it was hidden is signalled now."""
        self._place = place
        self._signal_shown()
        if place == "names" and "names" in self._stale:
            self._refresh_names()

    # Review: what goes into the run

    def _review_input(self) -> ReviewInput:
        assert self._key is not None
        profile, files = self.batches.profile(self._key), self._current_files()
        status = (self._statuses or {}).get("mkvtoolnix")
        return ReviewInput(
            items=self._items,
            media=self._key.media,
            tracks=profile.for_stage("tracks"),
            mux=profile.for_stage("mux"),
            run=self._current_files(self._run_preview) if files else (),
            full=files,
            groups_out=self.left_out.groups_of(self._key),
            files_out=self.left_out.files,
            blocks=blocked_stages(profile),
            mkvtoolnix_missing=self._statuses is not None and (status is None or status.state is not State.FOUND),
            filter=self._review_filter,
            failures=self._failures(),
        )

    @Property("QVariantMap", notify=review_changed)
    def review(self) -> dict[str, Any]:
        given = self._shown.get("review_input")
        return self._part("review", lambda: review(given)) if given is not None else {}

    def _get_review_filter(self) -> str:
        return self._review_filter

    def _set_review_filter(self, key: str) -> None:
        if key in FILTERS and key != self._review_filter:
            self._review_filter = key
            self._refresh()

    review_filter = Property(str, _get_review_filter, _set_review_filter, notify=plans_changed)

    @Slot(str, bool)
    def set_in_run(self, group: str, on: bool) -> None:
        """A group's "In this run": left out, it is planned as if its options asked for nothing; they stay."""
        if self._key is None or self.locked or group not in set(ChangeGroup):
            return
        self.left_out.set_group(self._key, ChangeGroup(group), not on)
        self._replan()

    @Slot(str, bool)
    def leave_out_file(self, path: str, out: bool) -> None:
        if self._key is None or self.locked or all(str(i.file.path) != path for i in self._items):
            return
        self._set_left_out([Path(path)], out)

    @Property(bool, notify=plans_changed)
    def batch_left_out(self) -> bool:
        return bool(self._items) and all(i.file.path in self.left_out.files for i in self._items)

    @Slot()
    def leave_out_batch(self) -> None:
        """The header's Leave out: every file of the batch, or all of them back when every one is out."""
        if self._key is not None and not self.locked:
            self._set_left_out([i.file.path for i in self._items], not self.batch_left_out)

    def _set_left_out(self, paths: list[Path], out: bool) -> None:
        self.left_out.set_files(paths, out)
        self.tree.set_left_out(self.left_out.files)
        self._refresh()

    @Slot(str)
    def set_original(self, original: str) -> None:
        """Where the originals of remuxed files go: the Recycle Bin or the keep folder beside them."""
        if self._key is None or self.locked or original not in set(Original):
            return
        mux = self.batches.profile(self._key).for_stage("mux")
        if mux.original != original:
            self.batches.copy(self._key).set_options("mux", replace(mux, original=Original(original)))
            self._copy_changed()

    # Apply

    @Property(QObject, constant=True)
    def jobs(self) -> Jobs:
        """The job of this window and the offer of unfinished ones; the drawer's Jobs tab reads it."""
        return self._job_view

    def _locked_paths(self) -> set[Path]:
        return set(self._applying.paths) if self._applying is not None else self.jobs.paths()

    @Property(bool, notify=batch_changed)
    def locked(self) -> bool:
        """The selected batch has a file in the job being applied: its choices wait until the job ends."""
        locked = self._locked_paths()
        return bool(locked) and any(i.file.path in locked for i in self._items)

    @Property(bool, notify=apply_changed)
    def applying(self) -> bool:
        return self._applying is not None or self.jobs.busy

    @Property(bool, notify=apply_changed)
    def can_apply(self) -> bool:
        """Only a plan that is on screen and current can be applied, one job at a time."""
        return (
            self._key is not None
            and not self.applying
            and not self._planner.busy
            and self._statuses is not None
            and bool(self._current_files(self._run_preview))
            and self.change_count > 0
        )

    @Property(str, notify=apply_changed)
    def apply_message(self) -> str:
        """Why the last Apply did not start, worded; empty after one that did."""
        return self._apply_message

    def _set_apply_message(self, text: str) -> None:
        self._apply_message = text
        self.apply_changed.emit()

    @Slot()
    def apply(self) -> None:
        """Plan the batch again with stamps on a pool thread; `_on_stamped` decides whether it may run."""
        if not self.can_apply or self._key is None or self._run_preview is None:
            return
        profile = self.batches.profile(self._key)
        stages = tuple(self._make_pipeline(self._statuses or {}))
        blocked = frozenset(blocked_stages(profile)) & {s.id for s in stages}
        items = tuple(self._items)
        head = heading(self._key, items)
        self._applying = _Applying(
            paths=frozenset(i.file.path for i in items),
            profile=profile,
            stages=stages,
            blocked=blocked,
            groups=self.left_out.groups_of(self._key),
            out=frozenset(p for p in self.left_out.files if any(i.file.path == p for i in items)),
            live={f.item.file.path: f.plans for f in self._run_preview.files},
            name=tr("common.list_separator").join((head.over, head.title)) if self._key.season else head.title,
        )
        given, store = self._applying, self.jobs.store

        def work() -> Preview:
            return preview(
                items, profile, stages, blocked=given.blocked, left_out=given.groups, finished=store.is_finished
            )

        job = BackgroundJob(work, self)
        job.finished.connect(self._on_stamped)
        job.failed.connect(self._on_stamp_failed)
        self._jobs.add(job)
        self._apply_message = ""
        self._on_lock_changed()
        job.start()

    def _on_stamped(self, stamped: Preview) -> None:
        given, self._applying = self._applying, None
        self._forget_job(self.sender())
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
        if changed:
            message = tr_plural("review.refused.changed", len(changed))
            self._read_again({path: path for path in changed})
        elif any(f.plans != given.live.get(f.item.file.path) for f in in_run):
            message = tr("review.refused.plans")
        elif not any(f.writes for f in in_run):
            message = tr("review.refused.nothing")
        else:
            try:
                job_id = create_job(
                    self.jobs.store,
                    stamped,
                    given.profile,
                    given.stages,
                    blocked=given.blocked,
                    left_out=given.groups,
                    left_out_files=given.out,
                )
            except StalePreviewError:
                message = tr("review.refused.plans")
            else:
                self.jobs.start(job_id, given.name)
        self._set_apply_message(message)
        self._on_lock_changed()

    def _on_stamp_failed(self, error: Exception) -> None:
        _log.error("The preview for Apply failed: %s", error)
        self._applying = None
        self._forget_job(self.sender())
        self._set_apply_message(tr("review.refused.error", error=str(error) or type(error).__name__))
        self._on_lock_changed()

    def _forget_job(self, job: object) -> None:
        if isinstance(job, BackgroundJob):
            self._jobs.discard(job)
            job.deleteLater()

    def _on_lock_changed(self) -> None:
        self.batch_changed.emit()
        self.apply_changed.emit()

    def _job_pipeline(self) -> tuple[Sequence[Stage], Read]:
        """The stages and the reader a job runs with: those of the programs found now."""
        return tuple(self._make_pipeline(self._statuses or {})), self._read

    def _read(self, path: Path) -> MediaFile:
        if self._read_file is not None:
            return self._read_file(path)
        return probe_file(path, programs_from(self._statuses or {}))

    def _names_of(self, path: Path) -> tuple[str, str]:
        """A job row's number and title, from the library when the file is in it."""
        item = self.model.library.item(path)
        return (item_number(item), item_title(item)) if item is not None else ("", path.name)

    def _on_job_ended(self, result: JobResult | None) -> None:
        """Read the written files again, so the window shows them as they are now, and unlock the batch."""
        self._on_lock_changed()
        if result is None:
            return
        written: dict[Path, Path] = {}
        gone: list[Path] = []
        for record in result.steps:
            if record.state is StepState.DONE:
                written[record.path] = record.written or written.get(record.path, record.path)
            if isinstance(record.detail, MuxResult):
                gone += record.detail.taken
        self._read_again(written, gone)

    def _read_again(self, paths: dict[Path, Path], gone: Sequence[Path] = ()) -> None:
        """Read files again on a pool thread, keyed by the path the library knows them by; a file that cannot be read
        keeps what was read before until the next load."""
        known = {i.file.path for i in self.model.library.items}
        targets = {old: new for old, new in paths.items() if old in known}
        if not targets and not gone:
            return
        read = self._read

        def work() -> tuple[dict[Path, MediaFile], tuple[Path, ...]]:
            files = {}
            for old, new in targets.items():
                try:
                    files[old] = read(new)
                except Exception:  # one unreadable file does not keep the others from the window
                    _log.exception("Could not read %s again", new)
            return files, tuple(gone)

        job = BackgroundJob(work, self)
        job.finished.connect(self._on_read_again)
        job.failed.connect(self._forget_sender)
        self._jobs.add(job)
        job.start()

    def _on_read_again(self, result: tuple[dict[Path, MediaFile], tuple[Path, ...]]) -> None:
        self._forget_job(self.sender())
        files, gone = result
        self.model.replace_files(files, gone)
        # The batch is selected again, so it holds the files as read now; a file with a new name opens its season.
        index = self.tree.index_of(self._selected) if self._selected else QModelIndex()
        if index.isValid():
            self.select(index)
        else:
            self._select_first()

    def _forget_sender(self, error: Exception) -> None:
        _log.error("Reading files again failed: %s", error)
        self._forget_job(self.sender())

    # Programs

    @Slot()
    def refresh_programs(self) -> None:
        # A child with bound slots: a check that ends after the window is gone is deleted with it and reaches nothing.
        job = BackgroundJob(self._check, self)
        job.finished.connect(self._on_statuses)
        job.failed.connect(self._on_check_failed)
        self._jobs.add(job)
        job.start()

    def _on_check_failed(self, error: Exception) -> None:
        _log.error("Checking the programs failed: %s", error)
        self._forget_job(self.sender())
        self._set_statuses({})

    def _on_statuses(self, statuses: Statuses) -> None:
        self._forget_job(self.sender())
        self._set_statuses(statuses)

    def _set_statuses(self, statuses: Statuses) -> None:
        self._statuses = statuses
        self.programs_changed.emit()
        self._replan()  # which stages plan depends on the programs found
        if not self._offered:
            # Jobs are offered once the programs are known, since resuming one runs them.
            self._offered = True
            self.jobs.check_unfinished()

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
        """ "Get it": Settings opens on Programs at that program's row; its checks refresh the statuses here."""
        self._get_program(spec_id)

    # Command palette

    def _get_palette_query(self) -> str:
        return self._palette_query

    def _set_palette_query(self, text: str) -> None:
        if text != self._palette_query:
            self._palette_query = text
            self.palette_changed.emit()

    palette_query = Property(str, _get_palette_query, _set_palette_query, notify=palette_changed)

    @Property(list, notify=palette_changed)
    def palette(self) -> list[dict[str, Any]]:
        """The palette's results for the query: actions, files, the batch's tracks and tokens, best first."""
        return [
            {"kind": e.kind, "key": e.key, "label": e.label, "detail": e.detail}
            for e in search(self._palette_query, self._palette_entries())
        ]

    def _palette_entries(self) -> list[Entry]:
        batch, edited = self._key is not None, self.profile_edited
        places = [key for key, _icon, later in WORKSPACE_TABS if not later]
        actions = [
            Entry("action", "open_folder", tr("palette.action.open_folder")),
            Entry("action", "add_files", tr("palette.action.add_files")),
            *(
                Entry("action", f"place.{key}", tr("palette.action.place", place=tr(f"workspace.tab.{key}")), "", batch)
                for key in places
            ),
            Entry("action", "drawer", tr("palette.action.drawer")),
            Entry(
                "action",
                "save_profile",
                tr("palette.action.save_profile"),
                self.profile,
                edited and not self.profile_read_only,
            ),
            Entry("action", "discard", tr("palette.action.discard"), self.profile, edited),
            *(
                Entry("action", f"settings.{key}", tr("palette.action.settings", section=tr(f"prefs.section.{key}")))
                for key, _icon in SECTIONS
            ),
        ]
        files = [
            Entry("file", str(item.file.path), item_title(item) or item.file.path.stem, item.file.path.stem)
            for item in self.model.library.items
        ]
        tracks = [
            Entry(
                "track",
                str(h["id"]),
                " · ".join(str(p) for p in (h["code"], h["title"], h["name"]) if p),
                tr(f"palette.track.{h['kind']}"),
            )
            for h in self._headers()
        ]
        custom = [t.name for t in self._custom()]
        tokens = [Entry("token", name, rail.token_label(name), f"{{{name}}}", batch) for name in [*TOKENS, *custom]]
        return [*actions, *files, *tracks, *tokens]

    @Slot(str, str)
    def palette_run(self, kind: str, key: str) -> None:
        """Run a result: an action, select a file, or take the window to a track's or a token's place."""
        self._set_palette_query("")
        if kind == "file":
            self._set_filter("")
            self._set_needs_look_only(False)
            index = self.tree.index_of(key)
            if index.isValid():
                self.select(index)
        elif kind == "track":
            self.palette_asked.emit("place", "tracks")
        elif kind == "token":
            self._set_token_query(key)
            self.palette_asked.emit("place", "names")
        elif key.startswith("place."):
            self.palette_asked.emit("place", key.removeprefix("place."))
        elif key.startswith("settings."):
            self._settings.open(key.removeprefix("settings."))
        else:
            run = {
                "open_folder": self.choose_folder,
                "add_files": self.choose_files,
                "save_profile": self.save_profile,
                "discard": self.discard_profile,
                "drawer": lambda: self.palette_asked.emit("drawer", ""),
            }.get(key)
            if run is not None:
                run()

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

    @Slot(result=int)
    def overview_tracks_height(self) -> int:
        """The height the user gave Overview's tracks box, 0 when none."""
        return load_settings().value.overview_tracks_height

    @Slot(int)
    def save_overview_tracks_height(self, height: int) -> None:
        settings = load_settings().value
        if height == settings.overview_tracks_height:
            return
        try:
            save_settings(replace(settings, overview_tracks_height=height))
        except OSError:
            _log.exception("Could not save the height of the tracks box")

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
