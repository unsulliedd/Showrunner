"""App-wide values that belong to the installation rather than to a profile."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from showrunner.app.options.serialization import Loaded, LoadWarning, WarningKind, from_sparse, to_sparse
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME
from showrunner.app.storage.files import write_json_atomic
from showrunner.app.storage.paths import settings_path

FORMAT_VERSION = 1


@dataclass(frozen=True)
class AppSettings:
    active_profile: str = DEFAULT_PROFILE_NAME
    last_folders: list[str] = field(default_factory=list)
    # Opaque to this layer: whatever string the window produces and later restores.
    window_geometry: str = ""


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
