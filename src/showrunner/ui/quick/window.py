"""The controller behind the Qt Quick window: the one object QML reads as `app`.

It holds no logic of its own. It builds the parts of the window, each a concern of its own, relays their signals, and
forwards every property and slot QML uses to the part that owns it. The parts:

- `Workspace`: the open place, its live plan and what the workspace views show of it; every other part reads it.
- `Run`: Review's run, Apply, the queue hand-off and reading written files again.
- `Folders`: reading folders, the filter, Home, Recent, Close folder and Remove from list.
- `Places`: the profile pill, the library row's menu, keep, exclude and Discard changes.
- `Choices`: track choices and rules; `Templates`: the Names place and Tokens panel.
- `FoundPrograms`: the programs found and MKVToolNix's languages; `CommandPalette`; `Sizes`.

A part references only the parts below it in that list, which it takes when it is built, never the window. Qt takes a
property's notify signal only from the class that declares the property, so every signal QML hears is declared here
and repeats the part's own signal of the same name.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QByteArray, QModelIndex, QObject, QThreadPool, Signal, Slot

from showrunner.app.batches.batch import Batches
from showrunner.app.batches.leave_out import LeftOut
from showrunner.app.jobs.run import Read
from showrunner.app.jobs.store import JobStore
from showrunner.app.library.loader import LibraryLoader
from showrunner.app.profiles.store import ProfileStore
from showrunner.app.storage.paths import jobs_path
from showrunner.ui.library.model import LibraryModel
from showrunner.ui.quick.choices import Choices
from showrunner.ui.quick.cleanup_editor import CleanupEditor
from showrunner.ui.quick.commands import CommandPalette
from showrunner.ui.quick.folders import Folders
from showrunner.ui.quick.found import FoundPrograms, check_shown
from showrunner.ui.quick.jobs import Jobs
from showrunner.ui.quick.languages import LanguagePicker
from showrunner.ui.quick.library import LibraryTree
from showrunner.ui.quick.lines import LinesPanel
from showrunner.ui.quick.places import Places
from showrunner.ui.quick.queue import Queue
from showrunner.ui.quick.rule_editor import RuleEditor
from showrunner.ui.quick.run import Run
from showrunner.ui.quick.settings import Settings
from showrunner.ui.quick.sizes import Sizes, available_screens
from showrunner.ui.quick.subtitles import SubtitleSettings
from showrunner.ui.quick.templates import Templates
from showrunner.ui.quick.window_state import Rect
from showrunner.ui.quick.workspace import SAVE_DELAY_MS, MakePipeline, Statuses, Workspace, default_pipeline

# How long closing the window waits for a cancelled job to stop its program and leave the files in a known place.
STOP_WAIT_MS = 10_000


def _property(kind: object, part: str, name: str, notify: Signal, *, writable: bool = False) -> Any:
    """A property of the window that reads, and when `writable` sets, the attribute `name` of the part `part`."""

    def get(self: QObject) -> Any:
        return getattr(getattr(self, part), name)

    def put(self: QObject, value: Any) -> None:
        setattr(getattr(self, part), name, value)

    return Property(kind, get, put if writable else None, notify=notify)


def _slot(part: str, name: str, *types: object, result: object = None, qt_name: str = "") -> Any:
    """A slot of the window, with the Qt types QML calls it with, that calls the method `name` of the part `part`;
    `qt_name` is the slot's own name where it differs from the method's."""

    def call(self: QObject, *args: Any) -> Any:
        return getattr(getattr(self, part), name)(*args)

    call.__name__ = qt_name or name  # the name the slot has in Qt's meta-object
    return (Slot(*types, result=result) if result is not None else Slot(*types))(call)


class WindowController(QObject):
    library_changed = Signal()
    needs_look_changed = Signal()
    loading_changed = Signal()
    programs_changed = Signal()
    recent_changed = Signal()
    home_changed = Signal()  # Home was asked for or left, or the library became empty or not
    batch_changed = Signal()
    filter_changed = Signal()
    plans_changed = Signal()  # the live plan or the choices of the selected batch changed
    planning_changed = Signal()
    names_changed = Signal()  # what the Names place or the Tokens panel shows changed
    subtitles_changed = Signal()  # what the Subtitles place shows changed
    lines_changed = Signal()  # what the Lines panel shows changed
    # What one place shows changed; each is emitted only while its place shows, and on switching to it.
    overview_changed = Signal()
    matrix_changed = Signal()
    review_changed = Signal()
    apply_changed = Signal()  # whether Apply can start, or why it did not
    palette_changed = Signal()
    palette_asked = Signal(str, str)  # the palette asks the window for a place ("place", key) or the drawer
    discard_asked = Signal()  # Discard changes was chosen: the window asks its question
    revert_asked = Signal()  # the profile pill's Revert was chosen: the window asks its question

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
        screens: Callable[[], Sequence[Rect]] = available_screens,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        # The lock is read through `run`, built next, so a test can stand in for it there.
        self.workspace = Workspace(
            store=store or ProfileStore(),
            make_pipeline=make_pipeline,
            locked_paths=lambda: self.run.locked_paths(),
            parent=self,
        )
        workspace = self.workspace
        self.run = Run(workspace, jobs or JobStore(jobs_path()), read, parent=self)
        self.found = FoundPrograms(workspace, self.run.jobs, statuses, parent=self)
        self._language_picker = LanguagePicker(lambda: self.found.known_codes, parent=self)
        self.found.languages_read.connect(self._language_picker.refresh_languages)
        self.choices = Choices(workspace, self._language_picker, parent=self)
        self.templates = Templates(workspace, parent=self)
        self.subtitle_settings = SubtitleSettings(workspace, self._language_picker, parent=self)
        self.lines_panel = LinesPanel(workspace, parent=self)
        self._cleanup_editor = CleanupEditor(self.lines_panel.loaded, lambda: workspace.locked, parent=self)
        self._cleanup_editor.saved.connect(workspace.rules_changed)
        self.lines_panel.track_read.connect(self._cleanup_editor.refresh)
        self.subtitle_settings.editor_asked.connect(self._cleanup_editor.open)
        self._rule_editor = RuleEditor(
            lambda: workspace.own_tracks() if workspace.key is not None else None,
            workspace.set_tracks,
            lambda: workspace.locked,
            lambda: workspace.items,
            lambda: workspace.view,
            parent=self,
        )
        workspace.place_left.connect(self._rule_editor.close)  # as does the rule being written
        self.folders = Folders(workspace, self.run, loader=loader, clock=clock, parent=self)
        self.places = Places(workspace, self.run, self.folders, parent=self)
        for source, names in (
            (workspace, ("batch_changed", "plans_changed", "planning_changed", "apply_changed", "loading_changed")),
            (workspace, ("overview_changed", "matrix_changed", "review_changed")),
            (self.folders, ("filter_changed", "recent_changed", "home_changed")),
            (self.places, ("discard_asked", "revert_asked")),
            (self.templates, ("names_changed",)),
            (self.subtitle_settings, ("subtitles_changed",)),
            (self.lines_panel, ("lines_changed",)),
            (self.found, ("programs_changed",)),
        ):
            for name in names:
                getattr(source, name).connect(getattr(self, name))
        self.plans_changed.connect(self._rule_editor.refresh)
        self.batch_changed.connect(self._rule_editor.refresh)
        self._settings = Settings(self)
        self.look = self._settings.look
        self._settings.programs_view.statuses_changed.connect(self.found.refresh)
        self._get_program = get_program or self._settings.get_program
        self.commands = CommandPalette(workspace, self.folders, self.places, self.templates, self._settings, self)
        self.commands.palette_changed.connect(self.palette_changed)
        self.commands.palette_asked.connect(self.palette_asked)
        self.sizes = Sizes(screens)
        model = workspace.model
        model.library_changed.connect(self.library_changed)
        model.library_changed.connect(self.home_changed)
        model.library_changed.connect(workspace.refresh_excluded)
        model.library_changed.connect(self.needs_look_changed)
        model.library_changed.connect(self.loading_changed)  # whether the library can be closed
        model.marks_changed.connect(self.needs_look_changed)

    # What Python reaches: the start, the end, Settings and the tests

    @property
    def model(self) -> LibraryModel:
        return self.workspace.model

    @property
    def tree(self) -> LibraryTree:
        return self.workspace.tree

    @property
    def batches(self) -> Batches:
        return self.workspace.batches

    @property
    def left_out(self) -> LeftOut:
        return self.workspace.left_out

    @property
    def store(self) -> ProfileStore:
        return self.workspace.store

    def start(self) -> None:
        """Check the programs in the background; `restore_workspace` reads the last folders again."""
        self.found.refresh()

    def restore_workspace(self) -> None:
        self.folders.restore_workspace()

    def save_workspace(self) -> None:
        self.folders.save_workspace()

    def stop_jobs(self) -> None:
        """Cancel a running job as the window closes and wait for its program to stop. The mux stage removes its
        partial file and leaves the original untouched; an Apply's job is offered to resume at the next start, and a
        queue item waits in the queue, stopped part way."""
        self.run.queue.stop()
        if self.run.jobs.busy:
            self.run.jobs.cancel()
            QThreadPool.globalInstance().waitForDone(STOP_WAIT_MS)

    def add_paths(self, paths: list[Path], *, restoring: bool = False) -> None:
        self.folders.add_paths(paths, restoring=restoring)

    def profiles_edited(self) -> None:
        """Settings changed profile files: the selected batch plans again, and the pill and lists follow."""
        self.workspace.copy_changed()

    # Child objects QML reads

    @Property(QObject, constant=True)
    def library(self) -> LibraryTree:
        return self.workspace.tree

    @Property(QObject, constant=True)
    def settings(self) -> Settings:
        """The Settings dialog's side: General, Profiles, Programs, Appearance, Shortcuts and About."""
        return self._settings

    @Property(QObject, constant=True)
    def jobs(self) -> Jobs:
        """The job of this window and the offer of unfinished ones; the drawer's Jobs tab reads it."""
        return self.run.jobs

    @Property(QObject, constant=True)
    def queue(self) -> Queue:
        """The places queued to run one after another; the drawer's Queue tab reads it."""
        return self.run.queue

    @Property(QObject, constant=True)
    def rule_editor(self) -> RuleEditor:
        """The editor of a hand-written track rule, in the Rules panel."""
        return self._rule_editor

    @Property(QObject, constant=True)
    def cleanup_editor(self) -> CleanupEditor:
        """The editor of the cleanup rule sets, in a dialog of its own."""
        return self._cleanup_editor

    @Property(QObject, constant=True)
    def language_picker(self) -> LanguagePicker:
        """The picker a chip's badge and the Names place open."""
        return self._language_picker

    @Property(int, constant=True)
    def save_delay(self) -> int:
        """How long QML waits after the last move or resize before it saves the window's place, in milliseconds."""
        return SAVE_DELAY_MS

    # Library, Home and Recent

    loaded = _property(bool, "folders", "loaded", library_changed)
    needs_look = _property(int, "folders", "needs_look", needs_look_changed)
    busy = _property(bool, "folders", "busy", loading_changed)
    read_fraction = _property(float, "folders", "read_fraction", loading_changed)
    job_text = _property(str, "folders", "job_text", loading_changed)
    reading_open_batch = _property(bool, "folders", "reading_open_batch", loading_changed)
    can_change_library = _property(bool, "folders", "can_change_library", loading_changed)
    filter_text = _property(str, "folders", "filter_text", filter_changed, writable=True)
    needs_look_only = _property(bool, "folders", "needs_look_only", filter_changed, writable=True)
    home_shown = _property(bool, "folders", "home_shown", home_changed)
    recent = _property(list, "folders", "recent", recent_changed)
    choose_folder = _slot("folders", "choose_folder")
    choose_files = _slot("folders", "choose_files")
    add_urls = _slot("folders", "add_urls", list)
    open_recent = _slot("folders", "open_recent", str)
    close_folder = _slot("folders", "close_folder")
    refresh_library = _slot("folders", "refresh", qt_name="refresh_library")
    cancel_reading = _slot("folders", "cancel_reading")
    go_home = _slot("folders", "go_home")
    leave_home = _slot("folders", "leave_home")
    remove_place = _slot("folders", "remove_place")
    close_place_folders = _slot("folders", "close_place_folders")
    remove_recent = _slot("folders", "remove_recent", str)
    recent_actions = _slot("folders", "recent_actions", result=list)

    # Selection and the open place

    @Slot(QModelIndex)
    def select(self, index: QModelIndex) -> None:
        """Select a row, as the user does: Home gives way to the workspace."""
        self.folders.leave_home()
        self.workspace.select(index)

    selected = _property(str, "workspace", "selected", batch_changed)
    selected_index = _property(QModelIndex, "workspace", "selected_index", batch_changed)
    has_batch = _property(bool, "workspace", "has_batch", batch_changed)
    batch_kind = _property(str, "workspace", "batch_kind", batch_changed)
    batch = _property("QVariantMap", "workspace", "batch", batch_changed)
    locked = _property(bool, "workspace", "locked", batch_changed)
    change_count = _property(int, "workspace", "change_count", plans_changed)
    change_text = _property(str, "workspace", "change_text", plans_changed)
    workspace_tabs = _property(list, "workspace", "workspace_tabs", plans_changed)
    focus_path = _property(str, "workspace", "focus_path", plans_changed)
    planning = _property(bool, "workspace", "planning", planning_changed)
    overview = _property("QVariantMap", "workspace", "overview", overview_changed)
    matrix = _property("QVariantMap", "workspace", "matrix", matrix_changed)
    movie = _property("QVariantMap", "workspace", "movie", plans_changed)
    rules = _property(list, "workspace", "rules", plans_changed)
    inspector = _property("QVariantMap", "workspace", "inspector", plans_changed)
    side_tabs = _slot("workspace", "side_tabs", str, result=list)
    focus_file = _slot("workspace", "focus_file", str)
    cell_tip = _slot("workspace", "cell_tip", int, str, result=str)
    show_place = _slot("workspace", "show_place", str)
    pair_subtitle = _slot("workspace", "pair_subtitle", str, str)
    unpair_subtitle = _slot("workspace", "unpair_subtitle", str)
    pair_subtitle_instead = _slot("workspace", "pair_subtitle_instead", str, str)

    # Profile, the place menu, keep, exclude and discard

    profile = _property(str, "places", "profile", batch_changed)
    profile_edited = _property(bool, "places", "profile_edited", batch_changed)
    profiles = _property(list, "places", "profiles", batch_changed)
    profile_read_only = _property(bool, "places", "profile_read_only", batch_changed)
    revert_question = _property("QVariantMap", "places", "revert_question", batch_changed)
    place_actions = _property(list, "places", "place_actions", batch_changed)
    can_keep = _property(bool, "places", "can_keep", batch_changed)
    kept_text = _property(str, "places", "kept_text", batch_changed)
    field_marks = _property("QVariantMap", "places", "field_marks", batch_changed)
    place_excluded = _property(bool, "places", "place_excluded", batch_changed)
    can_discard = _property(bool, "places", "can_discard", batch_changed)
    discard_question = _property("QVariantMap", "places", "discard_question", batch_changed)
    switch_profile = _slot("places", "switch_profile", str)
    ask_revert = _slot("places", "ask_revert")
    discard_profile = _slot("places", "discard_profile")
    save_profile = _slot("places", "save_profile")
    save_profile_as = _slot("places", "save_profile_as", str, result=str)
    place_action = _slot("places", "place_action", str)
    keep_place = _slot("places", "keep_place")
    exclude_place = _slot("places", "exclude_place", bool)
    exclude_file = _slot("places", "exclude_file", str, bool)
    ask_discard = _slot("places", "ask_discard")
    discard_changes = _slot("places", "discard_changes")

    # Track choices

    untagged = _property("QVariantMap", "choices", "untagged", batch_changed)
    write_implied_flags = _property(bool, "choices", "write_implied_flags", batch_changed)
    flags_from_names = _property(bool, "choices", "flags_from_names", batch_changed)
    implied_nothing = _property(bool, "choices", "implied_nothing", plans_changed)
    track_name_rows = _slot("choices", "track_name_rows", int, result="QVariantList")
    toggle_name = _slot("choices", "toggle_name", int, str)
    toggle_file_track = _slot("choices", "toggle_file_track", int, str)
    track_missing = _slot("choices", "track_missing", int, result=str)
    track_held = _slot("choices", "track_held", int, result=str)
    toggle_keep = _slot("choices", "toggle_keep", int)
    toggle_flag = _slot("choices", "toggle_flag", int, str)
    restore = _slot("choices", "restore", int)
    move_rule = _slot("choices", "move_rule", int, int)
    move_track = _slot("choices", "move_track", int, int, result=int)
    pause_rule = _slot("choices", "pause_rule", int, bool)
    remove_rule = _slot("choices", "remove_rule", int)
    pick_language = _slot("choices", "pick_language", int)
    pick_untagged_language = _slot("choices", "pick_untagged_language")
    set_untagged_language = _slot("choices", "set_untagged_language", str)
    set_flags_from_names = _slot("choices", "set_flags_from_names", bool)
    set_write_implied_flags = _slot("choices", "set_write_implied_flags", bool)

    # Subtitles

    subtitles = _property("QVariantMap", "subtitle_settings", "subtitles", subtitles_changed)
    set_subtitle_choice = _slot("subtitle_settings", "set_choice", str, str, qt_name="set_subtitle_choice")
    follow_subtitles = _slot("subtitle_settings", "follow", str, qt_name="follow_subtitles")
    subtitles_as_it_is = _slot("subtitle_settings", "as_it_is", str, qt_name="subtitles_as_it_is")
    toggle_subtitle_item = _slot("subtitle_settings", "toggle_item", str, str, qt_name="toggle_subtitle_item")
    pick_reference = _slot("subtitle_settings", "pick_reference", str, qt_name="pick_reference")
    pick_model = _slot("subtitle_settings", "pick_model", str, qt_name="pick_model")
    set_sync_setting = _slot("subtitle_settings", "set_sync_setting", str, str, qt_name="set_sync_setting")
    pick_wanted_language = _slot("subtitle_settings", "pick_language", qt_name="pick_wanted_language")
    add_rule_set = _slot("subtitle_settings", "add_rule_set", str, qt_name="add_rule_set")
    add_translation_name = _slot("subtitle_settings", "add_name", str, qt_name="add_translation_name")
    edit_rule_sets = _slot("subtitle_settings", "edit_rule_sets", str, qt_name="edit_rule_sets")
    lines = _property("QVariantMap", "lines_panel", "view", lines_changed)
    pick_lines_file = _slot("lines_panel", "pick", int, qt_name="pick_lines_file")

    # Names

    names = _property("QVariantMap", "templates", "names", names_changed)
    tokens = _property("QVariantMap", "templates", "tokens", names_changed)
    token_query = _property(str, "templates", "token_query", names_changed, writable=True)
    pick_template = _slot("templates", "pick_template", str)
    start_template = _slot("templates", "start_template", str)
    clear_template = _slot("templates", "clear_template")
    rail_insert = _slot("templates", "rail_insert", int, str)
    rail_append = _slot("templates", "rail_append", str)
    rail_append_text = _slot("templates", "rail_append_text", str)
    rail_move = _slot("templates", "rail_move", int, int)
    rail_remove = _slot("templates", "rail_remove", int)
    rail_set_text = _slot("templates", "rail_set_text", int, str)
    rail_add_text = _slot("templates", "rail_add_text", int, str)
    rail_optional = _slot("templates", "rail_optional", int)
    rail_padding = _slot("templates", "rail_padding", int)
    set_space = _slot("templates", "set_space", str)
    set_episode_code_format = _slot("templates", "set_episode_code_format", str)
    add_token = _slot("templates", "add_token")
    edit_token = _slot("templates", "edit_token", int)
    edit_builtin = _slot("templates", "edit_builtin", str)
    set_value_map = _slot("templates", "set_value_map", str, int, str, str)
    rename_token = _slot("templates", "rename_token", int, str)
    set_token_kind = _slot("templates", "set_token_kind", int, str)
    set_token_text = _slot("templates", "set_token_text", int, str)
    set_token_source = _slot("templates", "set_token_source", int, str)
    remove_token = _slot("templates", "remove_token", int)

    # Review and Apply

    review = _property("QVariantMap", "run", "review", review_changed)
    review_filter = _property(str, "run", "review_filter", plans_changed, writable=True)
    applying = _property(bool, "run", "applying", apply_changed)
    can_apply = _property(bool, "run", "can_apply", apply_changed)
    apply_message = _property(str, "run", "apply_message", apply_changed)
    can_queue = _property(bool, "run", "can_queue", batch_changed)
    set_in_run = _slot("run", "set_in_run", str, bool)
    set_file_in_run = _slot("run", "set_file_in_run", str, bool)
    set_original = _slot("run", "set_original", str)
    apply = _slot("run", "apply")
    add_to_queue = _slot("run", "add_to_queue")

    # Programs

    programs = _property(list, "found", "programs", programs_changed)
    status_programs = _property(list, "found", "status_programs", programs_changed)
    refresh_programs = _slot("found", "refresh", qt_name="refresh_programs")

    @Slot(str)
    def get_program(self, spec_id: str) -> None:
        """ "Get it": Settings opens on Programs at that program's row; its checks refresh the statuses here."""
        self._get_program(spec_id)

    # Command palette

    palette_query = _property(str, "commands", "query", palette_changed, writable=True)
    palette = _property(list, "commands", "results", palette_changed)
    palette_run = _slot("commands", "run", str, str, qt_name="palette_run")

    # Window and panel sizes

    window_state = _slot("sizes", "window_state", result="QVariantMap")
    save_window_state = _slot("sizes", "save_window_state", int, int, int, int, bool)
    overview_tracks_height = _slot("sizes", "overview_tracks_height", result=int)
    save_overview_tracks_height = _slot("sizes", "save_overview_tracks_height", int)
    subtitles_rows_height = _slot("sizes", "subtitles_rows_height", result=int)
    save_subtitles_rows_height = _slot("sizes", "save_subtitles_rows_height", int)
    matrix_files = _slot("sizes", "matrix_files", result=str)
    save_matrix_files = _slot("sizes", "save_matrix_files", str)
    panel_state = _slot("sizes", "panel_state", str, result=QByteArray)
    save_panel_state = _slot("sizes", "save_panel_state", str, QByteArray)
