"""Locations of the app data folder and the files inside it."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

HOME_ENV_VAR = "SHOWRUNNER_HOME"
_APP_NAME = "Showrunner"


def data_dir() -> Path:
    """The app data folder: `SHOWRUNNER_HOME` when set, else the per-user data folder of the OS."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override).expanduser()
    # appauthor=False keeps Windows from nesting the folder as Showrunner\Showrunner.
    return Path(platformdirs.user_data_dir(_APP_NAME, appauthor=False))


def profiles_dir() -> Path:
    return data_dir() / "profiles"


def settings_path() -> Path:
    return data_dir() / "settings.json"
