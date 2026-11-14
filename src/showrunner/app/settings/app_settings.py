"""App-wide values that belong to the installation rather than to a profile."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME
from showrunner.app.storage.files import write_json_atomic
from showrunner.app.storage.paths import settings_path
from showrunner.core.options.serialization import Loaded, LoadWarning, WarningKind, from_sparse, to_sparse

FORMAT_VERSION = 1


class ThemeMode(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class Startup(StrEnum):
    LAST_WORKSPACE = "last-workspace"  # read the last folders again and select what was selected
    EMPTY = "empty"


@dataclass(frozen=True)
class AppSettings:
    active_profile: str = DEFAULT_PROFILE_NAME
    startup: Startup = Startup.LAST_WORKSPACE
    # The workspace: what the window had open when it closed, for the next start.
    last_folders: list[str] = field(default_factory=list)
    last_selection: str = ""  # the path of the selected video
    # The `{source}` of the batch (BluRay, WEB-DL, ...); empty guesses it from each file's name. Kept with the
    # workspace, not the profile, since it describes the files rather than how to treat them.
    batch_source: str = ""
    # Opaque to this layer: whatever string the window produces and later restores.
    window_geometry: str = ""
    # Widths of the panes of the main window, as the splitters report them; empty until the user has moved one.
    library_splitter: list[int] = field(default_factory=list)
    sheet_splitter: list[int] = field(default_factory=list)
    ui_language: str = "en"
    theme_mode: ThemeMode = ThemeMode.SYSTEM
    # External programs the user located by hand: program id to the program file or its folder.
    tool_paths: dict[str, str] = field(default_factory=dict)


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
