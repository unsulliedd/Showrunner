"""App-wide values that belong to the installation rather than to a profile."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from showrunner.app.storage.files import write_json_atomic
from showrunner.app.storage.paths import settings_path
from showrunner.core.options.serialization import Loaded, LoadWarning, WarningKind, from_sparse, to_sparse

FORMAT_VERSION = 1
RECENT_LIMIT = 8
# Fields that earlier versions wrote and nothing reads any more; dropped on load so old files load without warnings.
_RETIRED_KEYS = ("active_profile", "batch_source", "library_splitter", "sheet_splitter")


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
    startup: Startup = Startup.LAST_WORKSPACE
    # The workspace: what the window had open when it closed, for the next start.
    last_folders: list[str] = field(default_factory=list)
    last_selection: str = ""  # the library row selected: a video's path, or the names down to a show or season row
    # Opaque to this layer: the text the window produces and later restores (its place and whether it is maximized).
    window_geometry: str = ""
    # Panel sizes: split name to the split's own saved state, as base64.
    panel_sizes: dict[str, str] = field(default_factory=dict)
    # Height of the tracks box on Overview, set by the separator under it; 0 until the user has moved it.
    overview_tracks_height: int = 0
    # Height of the settings box on Subtitles, set by the separator under it; 0 until the user has moved it.
    subtitles_rows_height: int = 0
    # Widths of the file and subtitles-now columns of the Subtitles file list, set by their dividers; 0 until moved.
    subtitles_file_width: int = 0
    subtitles_now_width: int = 0
    # Which files the Tracks strip shows: "all", "differ" (each run of files that follow every track as one), or ""
    # until the user picks, when it folds the runs only where every file would not fit.
    matrix_files: str = ""
    # Folders opened before, newest first: path to when it was last opened, as an ISO date and time.
    recent_folders: dict[str, str] = field(default_factory=dict)
    ui_language: str = "en"
    # Dark is the default theme; light and following Windows are chosen in Appearance.
    theme_mode: ThemeMode = ThemeMode.DARK
    density: Density = Density.COMFORTABLE
    # External programs the user located by hand: program id to the program file or its folder.
    tool_paths: dict[str, str] = field(default_factory=dict)
    # The AI model that translates and re-splits where a place chooses none; empty until one is chosen. Kept with the
    # machine, since it names a model installed here.
    ai_model: str = ""
    # The cues a translation asks the model for at a time, and the cues before and after them sent as context. Larger
    # windows save little time and cost more when one falls back.
    translate_window: int = 40
    translate_context: int = 5


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
    for key in _RETIRED_KEYS:
        data.pop(key, None)
    if isinstance(version, int) and not isinstance(version, bool) and version > FORMAT_VERSION:
        warnings.append(LoadWarning(WarningKind.NEWER_FORMAT, "format"))
    return Loaded(from_sparse(AppSettings, data, "settings", warnings), warnings)


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    write_json_atomic(path if path is not None else settings_path(), {"format": FORMAT_VERSION, **to_sparse(settings)})
