"""The open place of the window: the selected row, its videos and focus, its working copy's choices, its live plan and
what the workspace views show of it.

Every other part of the window reads the open place from here and sets choices through `set_options`, so an edit
ends in one place: the views follow at once, a new plan starts on a pool thread, and the workspace file is saved.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex, QObject, QTimer, Signal

from showrunner.app.batches.batch import Batches, BatchKey, BatchKind
from showrunner.app.batches.leave_out import LeftOut
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.dependencies.service import mkvpropedit_from, programs_from, tesseract_from
from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.jobs.counts import implied_flags, tab_counts
from showrunner.app.jobs.groups import ChangeGroup, without
from showrunner.app.jobs.preview import FileOutcome, FilePreview, Preview, preview_each
from showrunner.app.jobs.stages import Stage, pipeline
from showrunner.app.library.library import Library, Mark
from showrunner.app.profiles.profile import Profile
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.media import MediaItem
from showrunner.stages.tracks import TrackRule, TracksOptions
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.library.model import Kind, LibraryModel
from showrunner.ui.quick.facts import Heading, heading
from showrunner.ui.quick.library import LibraryTree
from showrunner.ui.quick.plans import LivePlanner
from showrunner.ui.quick.review import ReviewInput, skipped, totals
from showrunner.ui.quick.tracks import BatchView, Column, Received

_log = logging.getLogger(__name__)

# The places of a workspace in the order of work, with their icons; `later` ones are drawn muted until their stage
# exists.
WORKSPACE_TABS: tuple[tuple[str, str, bool], ...] = (
    ("overview", "list", False),
    ("tracks", "audio", False),
    ("subtitles", "subs", False),
    ("names", "names", False),
    ("review", "eye", False),
    ("artwork", "image", True),
    ("chapters", "chapters", True),
)
# The places whose data is built only while they show, with the signal that tells QML it changed.
_PLACE_SIGNALS = {"overview": "overview_changed", "tracks": "matrix_changed", "review": "review_changed"}
# The side panel each place brings; Review takes the whole width.
SIDE_PANELS: dict[str, tuple[str, ...]] = {
    "overview": ("inspector", "chapters", "attachments"),
    "tracks": ("rules", "inspector"),
    "subtitles": ("lines", "inspector"),
    "names": ("tokens", "inspector"),
    "review": (),
}
# A choice is written to the workspace file this long after the last one, so a burst of clicks writes once.
SAVE_DELAY_MS = 400
# The tree dot of a file whose plan needs a decision, and of one with planned changes.
_LOOK_DOT, _PLANNED_DOT = "needs_look", "planned"
_LOOK = (FileOutcome.REFUSED, FileOutcome.NEEDS_REMUX, FileOutcome.UNWRITTEN)
_NO_STRIP = {form: {"files": [], "lines": [], "seasons": []} for form in ("all", "differ")} | {"differing": 0}

type Statuses = dict[str, DependencyStatus]
type MakePipeline = Callable[[Statuses], Sequence[Stage]]


def default_pipeline(statuses: Statuses) -> tuple[Stage, ...]:
    return pipeline(programs_from(statuses), mkvpropedit_from(statuses), tesseract=tesseract_from(statuses))


def place_key(kind: Kind, first: MediaItem, show: BatchKey | None) -> BatchKey:
    """The place a library row stands for, from its kind and its first video; `show` is the key of the show row it lies
    under, so every place in a show's row names the show as the row does."""
    if kind.is_video:
        key = BatchKey.file(first)
    elif kind in (Kind.SEASON, Kind.EXTRAS):
        key = BatchKey.of(first)
    elif kind is Kind.SHOW:
        key = BatchKey.of(first, whole_show=True)
    else:
        key = BatchKey.movies()
    return key.in_show(show) if show is not None else key


class Workspace(QObject):
    """The open place and everything built from it. The parts of the window hold this object, never copies of its
    state: the header cache keys on the identity of `items`, and the plan token on that of each options object."""

    batch_changed = Signal()
    plans_changed = Signal()  # the live plan or the choices of the selected batch changed
    planning_changed = Signal()
    apply_changed = Signal()  # whether Apply can start, or why it did not
    loading_changed = Signal()
    # What one place shows changed; each is emitted only while its place shows, and on switching to it.
    overview_changed = Signal()
    matrix_changed = Signal()
    review_changed = Signal()
    place_left = Signal()  # another place opened, or none: what belongs to the one left, like an open editor, closes
    row_selected = Signal()  # a row was selected, the same one again included
    rebuilt = Signal()  # the views were built again, or the focus moved: Names follows
    place_shown = Signal()  # the window shows another workspace place

    def __init__(
        self,
        *,
        store: ProfileStore,
        make_pipeline: MakePipeline,
        locked_paths: Callable[[], set[Path]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.model = LibraryModel(self)
        self.tree = LibraryTree(self)
        self.tree.setSourceModel(self.model)
        self.store = store
        self.batches: Batches = load_batches(store)
        self.statuses: Statuses | None = None
        self.rules_revision = 0  # counts the edits of the cleanup rules, which every plan that cleans depends on
        self.make_pipeline = make_pipeline
        self._locked_paths = locked_paths  # the files a job writes or that are read again after it
        self.selected = ""  # the row id of the selected row
        self.restore = ""  # the row selected when the window last closed
        self.key: BatchKey | None = None
        self.items: list[MediaItem] = []
        self._head: tuple[BatchKey, list[MediaItem], Heading] | None = None  # see `heading`
        self.focus: MediaItem | None = None  # the selected video inside the batch
        self._planner = LivePlanner(self)
        self._planner.planned.connect(self._on_planned)
        self._planner.busy_changed.connect(self.planning_changed)
        self._planner.busy_changed.connect(self.apply_changed)
        self.preview: Preview | None = None  # the live plan of the selected batch, once it arrived
        self.run_preview: Preview | None = None  # the same with the left-out groups emptied, as Apply runs it
        self.left_out = LeftOut()  # what this run alone leaves out; exclusion is saved and lives in `batches`
        self.excluded_files: frozenset[Path] = frozenset()  # every excluded video of the library
        self.review_filter = "all"
        self.view: BatchView | None = None
        self.shown: dict[str, Any] = {}  # what QML reads about the batch, built once per plan or choice
        # The parts of `shown` a single place shows, built on first read after a plan or choice.
        self._built: dict[str, Any] = {}
        self.place = "overview"  # the workspace place the window shows
        self._stale: set[str] = set()  # places whose change was not signalled while they were hidden
        self.marks: dict[Path, str] = {}  # tree dots from the live plans of every batch opened
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_batches)

    # Saving

    def save_soon(self) -> None:
        """Write the working copies a moment after the last edit."""
        self._save_timer.start()

    def save_batches(self) -> None:
        """Write every batch's working copy at once (the file is replaced whole), so a crash loses no choice."""
        self._save_timer.stop()
        try:
            save_batches(self.batches)
        except OSError:
            _log.exception("Could not save the workspace state")

    # Selection

    def select(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        self.selected = self.tree.row_id(index)
        source = self.tree.mapToSource(index)
        paths = self.model.video_paths(source)
        items = [item for path in paths if (item := self.model.library.item(path)) is not None]
        kind = self.model.kind(source)
        self.focus = items[0] if kind.is_video and items else None
        previous = self.key
        # An episode or a movie row is one file's own place: what is chosen there is that file's alone.
        self.key, self.items = (place_key(kind, items[0], self._show_of(source)), items) if items else (None, [])
        if self.key != previous:
            if previous is not None:
                self.batches.normalize(previous.root)  # its values are settled now that it is left
            self.place_left.emit()
        self.row_selected.emit()
        self.replan()
        self.batch_changed.emit()

    def _show_of(self, source: QModelIndex) -> BatchKey | None:
        """The show of the show row at or above a row of the library, named by its first video; None outside a show."""
        while source.isValid() and self.model.kind(source) is not Kind.SHOW:
            source = source.parent()
        first = self.model.library.item(self.model.video_paths(source)[0]) if source.isValid() else None
        return BatchKey.of(first, whole_show=True) if first is not None else None

    def reselect(self) -> None:
        """Select the selected row again, also when it stays, since a season or show may have gained or lost videos;
        the first row when it is gone."""
        current = self.tree.index_of(self.selected) if self.selected else QModelIndex()
        if current.isValid():
            self.select(current)
        else:
            self.select_first()

    def select_first(self) -> None:
        """The row selected when the window last closed, else the first row of the tree."""
        restored = self.tree.index_of(self.restore) if self.restore else QModelIndex()
        self.select(restored if restored.isValid() else self.tree.index(0, 0))

    def clear(self, library: Library) -> None:
        """Show `library`, which holds no videos, with nothing selected."""
        self.model.set_library(library)
        self.selected = self.restore = ""
        self.focus = self.preview = self.run_preview = None
        self.key, self.items = None, []
        self.place_left.emit()
        self.marks.clear()
        self.replan()
        self.batch_changed.emit()
        self.loading_changed.emit()

    def file_item(self, path: str) -> MediaItem | None:
        """The video of the open place at `path`, as QML names it."""
        return next((i for i in self.items if str(i.file.path) == path), None)

    @property
    def selected_index(self) -> QModelIndex:
        """The selected row in the tree as filtered now; invalid when the filter hides it."""
        return self.tree.index_of(self.selected) if self.selected else QModelIndex()

    @property
    def has_batch(self) -> bool:
        return self.key is not None

    @property
    def batch_kind(self) -> str:
        return self.key.kind.value if self.key is not None else ""

    @property
    def batch(self) -> dict[str, str]:
        if self.key is None:
            return {"over": "", "title": "", "facts": ""}
        head = self.heading()
        return {"over": head.over, "title": head.title, "facts": head.facts}

    def heading(self) -> Heading:
        """The open place's header, built once per selection: several bindings read it after every edit. A selection
        sets a new list of items, never changes the list in place."""
        assert self.key is not None
        if self._head is None or self._head[0] != self.key or self._head[1] is not self.items:
            self._head = (self.key, self.items, heading(self.key, self.items))
        return self._head[2]

    @property
    def locked(self) -> bool:
        """The selected batch has a file in the job being applied or being read again after it: its choices wait
        until the files are as they are on disk."""
        locked = self._locked_paths()
        return bool(locked) and any(i.file.path in locked for i in self.items)

    # The top bar and the tabs

    @property
    def change_count(self) -> int:
        """What Apply would write: the run plan's changes, without left-out groups and files."""
        return int(self.shown.get("totals", (0, 0))[0])

    @property
    def change_text(self) -> str:
        """The top bar's "68 changes in 10 files", "2 changes skipped this run" when only unticked ones are planned,
        or "Nothing to change yet"."""
        changes, files = self.shown.get("totals", (0, 0))
        if not changes:
            left_out = self.shown.get("skipped", 0)
            return tr_plural("top.skipped", left_out) if left_out else tr("top.nothing")
        return tr("top.changes_in", changes=tr_plural("top.changes", changes), files=tr_plural("top.files", files))

    @property
    def workspace_tabs(self) -> list[dict[str, Any]]:
        counts = self.shown.get("counts", {})
        per_place = {
            "tracks": counts.get("tracks", 0),
            "subtitles": counts.get("subtitles", 0),
            "names": counts.get("names", 0),
            "review": self.change_count,
        }
        return [
            {"key": key, "icon": icon, "count": per_place.get(key, 0), "later": later}
            for key, icon, later in WORKSPACE_TABS
        ]

    def side_tabs(self, place: str) -> list[dict[str, Any]]:
        """The side panel's tabs for a workspace place; Chapters and Attachments count the selected video's."""
        file = self.focus.file if self.focus is not None else (self.items[0].file if self.items else None)
        counts = {
            "chapters": len(file.chapters) if file is not None else 0,
            "attachments": len(file.attachments) if file is not None else 0,
        }
        return [{"key": key, "count": counts.get(key, -1)} for key in SIDE_PANELS.get(place, ())]

    # Choices of the open place

    def set_options(self, stage_id: str, options: Any, key: BatchKey | None = None) -> None:
        """Set the options of one stage of the open place, or of `key`, a place inside it."""
        assert self.key is not None
        if self.locked:
            return
        self.batches.set_options(key or self.key, stage_id, options)
        self.copy_changed()

    def rules_changed(self) -> None:
        """A cleanup rule set was written: the plans that clean are made again with it."""
        self.rules_revision += 1
        self.replan()

    def copy_changed(self) -> None:
        """Every edit of a working copy ends here: the views follow at once, a new plan starts, the file is saved."""
        self.replan()
        self.save_soon()
        self.batch_changed.emit()

    def tracks(self) -> TracksOptions:
        """The track options the batch plans with: its own choices over the ones it receives."""
        assert self.key is not None
        return self.batches.profile(self.key).for_stage("tracks")

    def own_tracks(self) -> TracksOptions:
        """The same with only the batch's own rules, which the Rules panel edits by place."""
        assert self.key is not None
        return self.batches.own_tracks(self.key)

    def set_tracks(self, options: TracksOptions) -> None:
        """Set the batch's own track options; `options.rules` are its own rules (`own_tracks`)."""
        self.set_options("tracks", options)

    def column(self, column: int) -> tuple[Column, dict[str, Any]] | None:
        if self.view is None or not 0 <= column < len(self.view.cols):
            return None
        return self.view.cols[column], self.headers()[column]

    # What the places show

    def focus_file(self, path: str) -> None:
        """Show one file of the batch in the Inspector. Only the focus moves: selecting the file in the tree would open
        the file's own place instead of the batch."""
        item = self.file_item(path)
        if item is None:
            return
        self.focus = item
        # Only the Inspector and the Names result follow the focus; rows, headers and Review stay as built.
        if self.shown:
            self.shown["inspector"] = self._inspector()
        self.plans_changed.emit()
        self.rebuilt.emit()

    @property
    def focus_path(self) -> str:
        """The file the Inspector and Names show: the focused one, else the batch's first."""
        focus = self.focus or (self.items[0] if self.items else None)
        return str(focus.file.path) if focus is not None else ""

    @property
    def planning(self) -> bool:
        return self._planner.busy

    def part(self, key: str, build: Callable[[], Any]) -> Any:
        """A part one place shows, built on its first read after a plan or choice."""
        if key not in self._built:
            self._built[key] = build()
        return self._built[key]

    def headers(self) -> list[dict[str, Any]]:
        return self.part("headers", self.view.headers) if self.view is not None else []

    def _rows(self) -> list[dict[str, Any]]:
        return self.part("rows", self.view.rows) if self.view is not None else []

    @property
    def overview(self) -> dict[str, Any]:
        """Chips by kind and one row per file, for a season, a show or a selection, under a lead that speaks of every
        file only where there are several."""
        groups = self.part("groups", self.view.groups) if self.view is not None else []
        lead = tr("overview.lead" if len(self.items) > 1 else "overview.lead_one")
        return {"groups": groups, "rows": self._rows(), "lead": lead}

    @property
    def matrix(self) -> dict[str, Any]:
        """The tracks as rows, each beside a strip of the files."""
        headers = self.headers()
        view = self.view
        strip = self.part("strip", lambda: view.strip(headers)) if view is not None else _NO_STRIP
        return {"headers": headers, "strip": strip}

    def cell_tip(self, column: int, path: str) -> str:
        """The tooltip of one file's cell under a track of the Tracks strip, built when the pointer is over it."""
        found = self.column(column)
        item = self.file_item(path)
        if found is None or item is None or self.view is None:
            return ""
        return self.view.tip(column, item, found[1])

    @property
    def movie(self) -> dict[str, Any]:
        """The movie's tracks as cards by kind."""
        return self.shown.get("movie", {"groups": []})

    @property
    def rules(self) -> list[dict[str, Any]]:
        return self.shown.get("rules", [])

    @property
    def inspector(self) -> dict[str, Any]:
        return self.shown.get("inspector", {})

    def current_files(self, plan: Preview | None = None) -> tuple[FilePreview, ...]:
        """The live plan's files when it was made for the batch's files as they are now."""
        plan = plan or self.preview
        paths = [i.file.path for i in self.items]
        if plan is None or [f.item.file.path for f in plan.files] != paths:
            return ()
        return plan.files

    # Live plans

    def replan(self) -> None:
        """Show the choices at once, then plan the batch again in the background."""
        self.refresh()
        if self.key is None:
            return
        statuses = self.statuses or {}
        stages = tuple(self.make_pipeline(statuses))
        items = tuple(self.items)
        profiles = self.batches.file_profiles(items, self.key)
        run_profiles = self.run_profiles(items, profiles)

        def work() -> tuple[Preview, Preview]:
            full = preview_each(items, profiles, stages, stamped=False)
            run = preview_each(items, run_profiles, stages, stamped=False) if run_profiles != profiles else full
            return full, run

        self._planner.request(self._plan_token(profiles), work)

    def _groups_out(self, items: Sequence[MediaItem]) -> dict[Path, frozenset[ChangeGroup]]:
        """The groups this run leaves out of each file, as its own place has them (`LeftOut`)."""
        assert self.key is not None
        return {i.file.path: self.left_out.groups_of(BatchKey.file(i).in_show(self.key)) for i in items}

    def run_profiles(self, items: Sequence[MediaItem], profiles: dict[Path, Profile]) -> dict[Path, Profile]:
        """Each file's options with the groups this run leaves out of it asking for nothing. Files that shared an
        options object and leave out the same groups share one again, so they are still planned together."""
        made: dict[tuple[int, frozenset[ChangeGroup]], Profile] = {}
        result = {}
        for path, groups in self._groups_out(items).items():
            profile = profiles[path]
            if groups and (id(profile), groups) not in made:
                emptied = profile
                for group in sorted(groups):
                    emptied = without(emptied, group)
                made[id(profile), groups] = emptied
            result[path] = made[id(profile), groups] if groups else profile
        return result

    def _plan_token(self, profiles: dict[Path, Profile] | None = None) -> tuple[Any, ...]:
        """What a plan was made for; a result for another token is out of date when it arrives. Each file's options
        count, read once per options object the files share, and the groups left out of each."""
        if self.key is None:
            return (None,)
        profiles = profiles if profiles is not None else self.batches.file_profiles(self.items, self.key)
        options = repr([p.options for p in {id(p): p for p in profiles.values()}.values()])
        groups = tuple(sorted(g) for g in self._groups_out(self.items).values())
        return (
            self.key,
            tuple(i.file.path for i in self.items),
            options,
            repr(self.statuses),
            groups,
            self.rules_revision,
        )

    def _on_planned(self, token: object, result: tuple[Preview, Preview]) -> None:
        if token != self._plan_token():
            return  # the batch or its choices changed while it was planned; a newer plan is on its way
        self.preview, self.run_preview = result
        for file in self.preview.files:
            path = file.item.file.path
            if file.outcome in _LOOK:
                self.marks[path] = _LOOK_DOT
            elif file.outcome is FileOutcome.CHANGES:
                self.marks[path] = _PLANNED_DOT
            else:
                self.marks.pop(path, None)
        self.model.set_plan_marks(self.marks)
        self.refresh()

    def refresh(self) -> None:
        """Build what QML reads about the batch from its items, its choices and the live plan if it is current. What
        only one place shows (rows, chips, headers, Review, Names) is built when read, and signalled only while that
        place shows, so a whole show's 300 rows are not built for places nobody looks at."""
        self._built = {}
        self._stale |= set(_PLACE_SIGNALS)
        if self.key is None:
            self.view, self.shown = None, {}
        else:
            files = self.current_files()
            profile = self.batches.profile(self.key)
            tracks = profile.for_stage("tracks")
            self.view = BatchView.build(
                self.items, tracks, files, self._failures(), self._received(), self._file_rules()
            )
            counts = dict.fromkeys(("tracks", "subtitles", "names"), 0)
            implied = 0
            for file in files:
                if file.item.file.path not in self.excluded_files:
                    for tab, count in tab_counts(file).items():
                        counts[tab] += count
                    implied += implied_flags(file)
            self.shown = {
                "rules": self.view.rules(),
                "counts": counts,
                "implied": implied if files else None,  # None while no plan is current
                "inspector": self._inspector(),
            }
            if self.key.kind is BatchKind.MOVIE and self.items:
                groups = self.view.card_groups(self.items[0])
                self.shown["movie"] = {"groups": groups}
            self.shown["review_input"] = given = self._review_input()
            self.shown["totals"] = totals(given)
            self.shown["skipped"] = skipped(given, self.shown["totals"][0])
        self.plans_changed.emit()
        self.apply_changed.emit()
        self._signal_shown()
        self.rebuilt.emit()

    def _received(self) -> Received:
        """Where each rule of the batch comes from, and what the batch receives, for the marks on chips and rules."""
        assert self.key is not None
        key, parent = self.key, self.key.parent
        if parent is None:
            return Received()
        origins = ["" if origin == key else origin.kind.value for origin in self.batches.origins(key)]
        received = self.batches.received(key)
        assert received is not None
        above = [] if self.batches.kept(key) else self.batches.origins(parent)
        paired = self.batches.field_origin(key, "tracks", "add_paired")
        over = self.batches.field_origin(parent, "tracks", "add_paired") if paired == key else None
        return Received(
            origins,
            received.for_stage("tracks"),
            [origin.kind.value for origin in above],
            paired_from=paired.kind.value if paired is not None and paired != key else "",
            paired_over=over.kind.value if over is not None else "",
        )

    def _file_rules(self) -> dict[str, list[TrackRule]]:
        """The track rules of each file's own place, to mark the lines whose file made its own choice; none where the
        open place is a file, which then holds them as its own."""
        assert self.key is not None
        if self.key.kind in (BatchKind.EPISODE, BatchKind.EXTRA, BatchKind.MOVIE):
            return {}
        return {str(path): rules for path, rules in self.batches.file_own_rules(self.items, self.key).items()}

    def _failures(self) -> dict[str, str]:
        """Why each file of the batch whose tracks could not be read was not read."""
        library = self.model.library
        return {str(i.file.path): reason for i in self.items if (reason := library.failure(i.file.path)) is not None}

    def _inspector(self) -> dict[str, Any]:
        focus = self.focus or (self.items[0] if self.items else None)
        if self.view is None or self.key is None or focus is None:
            return {}
        own = self.batches.profile(BatchKey.file(focus).in_show(self.key))
        return self.view.inspector(focus, own.for_stage("mux").original)

    def _signal_shown(self) -> None:
        signal = _PLACE_SIGNALS.get(self.place)
        if signal is not None and self.place in self._stale:
            self._stale.discard(self.place)
            getattr(self, signal).emit()

    def show_place(self, place: str) -> None:
        """The window shows another workspace place; what changed there while it was hidden is signalled now."""
        self.place = place
        self._signal_shown()
        self.place_shown.emit()

    # What goes into the run

    def _review_input(self) -> ReviewInput:
        assert self.key is not None
        profile, files = self.batches.profile(self.key), self.current_files()
        status = (self.statuses or {}).get("mkvtoolnix")
        return ReviewInput(
            items=self.items,
            media=self.key.media,
            tracks=profile.for_stage("tracks"),
            mux=profile.for_stage("mux"),
            run=self.current_files(self.run_preview) if files else (),
            full=files,
            groups_out=self.left_out.groups_of(self.key),
            held_inside={g: n for g in ChangeGroup if (n := self.left_out.held_inside(self.key, g))},
            files_out=self.files_out(),
            excluded=self.excluded_files,
            blocks=blocked_stages(profile),
            profiles=self.batches.file_profiles(self.items, self.key),
            mkvtoolnix_missing=self.statuses is not None and (status is None or status.state is not State.FOUND),
            filter=self.review_filter,
            failures=self._failures(),
            unsure=frozenset(i.file.path for i in self.items if self.model.library.mark(i.file.path) is Mark.UNSURE),
        )

    def files_out(self) -> frozenset[Path]:
        """The files of the open place that this run leaves out (unticked in Review), by their own places."""
        assert self.key is not None
        return frozenset(i.file.path for i in self.items if self.left_out.file_out(BatchKey.file(i).in_show(self.key)))

    # Exclusion

    def refresh_excluded(self) -> None:
        """Read which rows of the library are excluded, folders too, and which keep their files as they are, and tell
        the tree and the model."""
        model, rows, files, kept = self.model, set(), set(), set()

        def walk(parent: QModelIndex, show: BatchKey | None) -> None:
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                kind, paths = model.kind(index), model.video_paths(index)
                item = model.library.item(paths[0]) if paths else None
                if item is None:
                    continue
                key = place_key(kind, item, show)
                if self.batches.is_excluded(key):
                    rows.add(self.tree.source_row_id(index))
                    if kind.is_video:
                        files.add(item.file.path)
                if self.batches.kept(key):
                    kept.add(self.tree.source_row_id(index))
                walk(index, key if kind is Kind.SHOW else show)

        walk(QModelIndex(), None)
        self.excluded_files = frozenset(files)
        self.tree.set_excluded(rows)
        self.tree.set_kept(kept)
        model.set_excluded(files)
