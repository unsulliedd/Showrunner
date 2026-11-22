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


def results_dir() -> Path:
    """Where the results of slow subtitle work are kept for a resume."""
    return data_dir() / "subtitles"


def theme_path() -> Path:
    return data_dir() / "theme.json"


def workspace_path() -> Path:
    """What the window had open beyond the settings: each batch's working copy of its profile."""
    return data_dir() / "workspace.json"


def read_cache_path() -> Path:
    """What was read from each video, so opening the same folders again reads only the files that changed."""
    return data_dir() / "read_cache.json"


def jobs_path() -> Path:
    """The database of job progress."""
    return data_dir() / "jobs.sqlite3"


def tools_dir() -> Path:
    """Where downloaded programs go, one folder per program."""
    return data_dir() / "tools"
