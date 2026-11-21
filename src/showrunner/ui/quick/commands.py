"""The command palette's side of the window: the query, the entries gathered from the other parts, and running the one
picked. How a query ranks the entries is in `palette`."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from showrunner.core.naming import TOKENS
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.quick import names as rail
from showrunner.ui.quick.folders import Folders
from showrunner.ui.quick.palette import Entry, search
from showrunner.ui.quick.places import Places
from showrunner.ui.quick.settings import SECTIONS, Settings
from showrunner.ui.quick.templates import Templates
from showrunner.ui.quick.tracks import item_title
from showrunner.ui.quick.workspace import WORKSPACE_TABS, Workspace


class CommandPalette(QObject):
    palette_changed = Signal()
    palette_asked = Signal(str, str)  # the palette asks the window for a place ("place", key) or the drawer

    def __init__(
        self,
        workspace: Workspace,
        folders: Folders,
        places: Places,
        templates: Templates,
        settings: Settings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._workspace = workspace
        self._folders = folders
        self._places = places
        self._templates = templates
        self._settings = settings
        self._query = ""

    @property
    def query(self) -> str:
        return self._query

    @query.setter
    def query(self, text: str) -> None:
        if text != self._query:
            self._query = text
            self.palette_changed.emit()

    @property
    def results(self) -> list[dict[str, Any]]:
        """The palette's results for the query: actions, files, the batch's tracks and tokens, best first."""
        return [
            {"kind": e.kind, "key": e.key, "label": e.label, "detail": e.detail}
            for e in search(self._query, self._entries())
        ]

    def _entries(self) -> list[Entry]:
        workspace, places = self._workspace, self._places
        batch, edited = workspace.key is not None, places.profile_edited
        loaded = self._folders.loaded
        tabs = [key for key, _icon, later in WORKSPACE_TABS if not later]
        actions = [
            Entry("action", "open_folder", tr("palette.action.open_folder")),
            Entry("action", "add_files", tr("palette.action.add_files")),
            Entry("action", "close_folder", tr("palette.action.close_folder"), "", loaded),
            Entry("action", "home", tr("palette.action.home"), "", loaded and not self._folders.home_shown),
            *(
                Entry("action", f"place.{key}", tr("palette.action.place", place=tr(f"workspace.tab.{key}")), "", batch)
                for key in tabs
            ),
            Entry("action", "drawer", tr("palette.action.drawer")),
            Entry(
                "action",
                "save_profile",
                tr("palette.action.save_profile"),
                places.profile,
                edited and not places.profile_read_only,
            ),
            Entry("action", "discard", tr("palette.action.discard"), workspace.batch["title"], places.can_discard),
            Entry(
                "action",
                "include" if places.place_excluded else "exclude",
                tr("palette.action.include" if places.place_excluded else "palette.action.exclude"),
                workspace.batch["title"],
                batch and not workspace.locked,
            ),
            *(
                Entry("action", f"settings.{key}", tr("palette.action.settings", section=tr(f"prefs.section.{key}")))
                for key, _icon in SECTIONS
            ),
        ]
        files = [
            Entry("file", str(item.file.path), item_title(item) or item.file.path.stem, item.file.path.stem)
            for item in workspace.model.library.items
        ]
        tracks = [
            Entry(
                "track",
                str(h["id"]),
                f" {tr('status.separator')} ".join(str(p) for p in (h["code"], h["title"], h["name"]) if p),
                tr(f"palette.track.{h['kind']}"),
            )
            for h in workspace.headers()
        ]
        custom = [t.name for t in self._templates.custom()]
        tokens = [Entry("token", name, rail.token_label(name), f"{{{name}}}", batch) for name in [*TOKENS, *custom]]
        return [*actions, *files, *tracks, *tokens]

    def run(self, kind: str, key: str) -> None:
        """Run a result: an action, select a file, or take the window to a track's or a token's place."""
        folders, places = self._folders, self._places
        self.query = ""
        if kind == "file":
            folders.filter_text = ""
            folders.needs_look_only = False
            index = self._workspace.tree.index_of(key)
            if index.isValid():
                folders.leave_home()
                self._workspace.select(index)
        elif kind == "track":
            folders.leave_home()
            self.palette_asked.emit("place", "tracks")
        elif kind == "token":
            folders.leave_home()
            self._templates.token_query = key
            self.palette_asked.emit("place", "names")
        elif key.startswith("place."):
            folders.leave_home()
            self.palette_asked.emit("place", key.removeprefix("place."))
        elif key.startswith("settings."):
            self._settings.open(key.removeprefix("settings."))
        else:
            run = {
                "open_folder": folders.choose_folder,
                "add_files": folders.choose_files,
                "close_folder": folders.close_folder,
                "home": folders.go_home,
                "save_profile": places.save_profile,
                "discard": places.ask_discard,
                "exclude": lambda: places.exclude_place(True),
                "include": lambda: places.exclude_place(False),
                "drawer": lambda: self.palette_asked.emit("drawer", ""),
            }.get(key)
            if run is not None:
                run()
