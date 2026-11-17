"""The workspace state file: every root's working copy of its profile, every nearer place's own choices and the places
excluded from every run, so unsaved choices and exclusions survive a restart. A file of format 1 held a whole profile
per batch; `Batches.from_json` reads it as well."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from showrunner.app.batches.batch import Batches
from showrunner.app.profiles.store import ProfileStore
from showrunner.app.storage.files import write_json_atomic
from showrunner.app.storage.paths import workspace_path

FORMAT_VERSION = 2

_log = logging.getLogger(__name__)


def load_batches(store: ProfileStore, path: Path | None = None) -> Batches:
    """A missing file gives no batches; an unreadable one is logged and gives no batches either."""
    path = path if path is not None else workspace_path()
    if not path.is_file():
        return Batches(store)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _log.warning("Workspace state %s is unreadable", path)
        return Batches(store)
    return Batches.from_json(store, data.get("batches") if isinstance(data, dict) else None)


def save_batches(batches: Batches, path: Path | None = None) -> None:
    write_json_atomic(
        path if path is not None else workspace_path(), {"format": FORMAT_VERSION, "batches": batches.to_json()}
    )
