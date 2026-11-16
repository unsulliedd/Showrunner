from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from showrunner.app.storage.paths import HOME_ENV_VAR


@pytest.fixture(autouse=True)
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The window saves settings and the theme as the user changes them; tests must never touch the real data folder.
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def deleted_at_end(data_home: Path) -> Iterator[None]:
    """Objects a test let go with `deleteLater` are deleted when it ends, while its data folder is still set. Qt
    deletes them only inside an event loop, so a window controller lived on with its timers, and its pending
    workspace save landed in the next test's data folder, which then started with the old test's choices."""
    yield
    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
