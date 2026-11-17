"""App-wide values that belong to the installation rather than to a profile."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME
from showrunner.app.storage.files import write_json_atomic
from showrunner.app.storage.paths import settings_path
from showrunner.core.options.serialization import Loaded, LoadWarning, WarningKind, from_sparse, to_sparse

FORMAT_VERSION = 1
RECENT_LIMIT = 8


class ThemeMode(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class Density(StrEnum):
    COMFORTABLE = "comfortable"
    COMPACT = "compact"  # shorter rows and panel headers, for long seasons on small screens


class Startup(StrEnum):
    LAST_WORKSPACE = "last-workspace"  # read the last folders again and select what was selected
    EMPTY = "empty"


@dataclass(frozen=True)
class AppSettings:
    active_profile: str = DEFAULT_PROFILE_NAME
    startup: Startup = Startup.LAST_WORKSPACE
    # The workspace: what the window had open when it closed, for the next start.
    last_folders: list[str] = field(default_factory=list)
    last_selection: str = ""  # the library row selected: a video's path, or the names down to a show or season row
    # The `{source}` of the batch (BluRay, WEB-DL, ...); empty guesses it from each file's name. Kept with the
    # workspace, not the profile, since it describes the files rather than how to treat them.
    batch_source: str = ""
    # Opaque to this layer: whatever string the window produces and later restores.
    window_geometry: str = ""
    # Widths of the panes of the main window, as the splitters report them; empty until the user has moved one.
    library_splitter: list[int] = field(default_factory=list)
    sheet_splitter: list[int] = field(default_factory=list)
    # Panel sizes of the Qt Quick window: split name to the split's own saved state, as base64.
    panel_sizes: dict[str, str] = field(default_factory=dict)
    # Height of the tracks box on Overview, set by the separator under it; 0 until the user has moved it.
    overview_tracks_height: int = 0
    # Folders opened before, newest first: path to when it was last opened, as an ISO date and time.
    recent_folders: dict[str, str] = field(default_factory=dict)
    ui_language: str = "en"
    # Dark is the approved theme; light and following Windows are chosen in Appearance.
    theme_mode: ThemeMode = ThemeMode.DARK
    density: Density = Density.COMFORTABLE
    # External programs the user located by hand: program id to the program file or its folder.
    tool_paths: dict[str, str] = field(default_factory=dict)


def with_recent(recent: dict[str, str], folders: Iterable[str], when: datetime) -> dict[str, str]:
    """`recent` with `folders` moved to the front as opened at `when`, keeping the newest `RECENT_LIMIT`."""
    opened = when.isoformat(timespec="seconds")
    fresh = {folder: opened for folder in folders}
    rest = {folder: time for folder, time in recent.items() if folder not in fresh}
    return dict(list({**fresh, **rest}.items())[:RECENT_LIMIT])


def load_settings(path: Path | None = None) -> Loaded[AppSettings]:
    """A missing file gives defaults silently; an unreadable one gives defaults and a warning."""
    path = path if path is not None else settings_path()
    if not path.is_file():
        return Loaded(AppSettings())
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Loaded(AppSettings(), [LoadWarning(WarningKind.UNREADABLE, str(path))])
    if not isinstance(data, dict):
        return Loaded(AppSettings(), [LoadWarning(WarningKind.UNREADABLE, str(path))])
    warnings: list[LoadWarning] = []
    version = data.pop("format", None)
    if isinstance(version, int) and not isinstance(version, bool) and version > FORMAT_VERSION:
        warnings.append(LoadWarning(WarningKind.NEWER_FORMAT, "format"))
    return Loaded(from_sparse(AppSettings, data, "settings", warnings), warnings)


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    write_json_atomic(path if path is not None else settings_path(), {"format": FORMAT_VERSION, **to_sparse(settings)})
