from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool

from showrunner.app.storage.paths import HOME_ENV_VAR

POOL_WAIT_MS = 10_000
# Each round delivers what the pool's work sent back, which may start more work (a plan after a program check).
POOL_ROUNDS = 10


@pytest.fixture(autouse=True)
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The window saves settings and the theme as the user changes them; tests must never touch the real data folder.
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def deleted_at_end(data_home: Path) -> Iterator[None]:
    """Work a test left on the thread pool ends, its results are delivered, and the objects the test let go with
    `deleteLater` are deleted, all when the test ends, while its data folder is still set.

    Results come back from the pool as queued signals, delivered whenever events are next processed: a check or a
    plan still running at the end reached its window during the next test, with the next test's data folder set.
    Qt deletes objects only inside an event loop, so a window controller lived on with its timers, and its pending
    workspace save landed in the next test's data folder, which then started with the old test's choices."""
    yield
    if QCoreApplication.instance() is None:
        return
    pool = QThreadPool.globalInstance()
    try:
        for _ in range(POOL_ROUNDS):
            # A job held half way (a stand-in stage waiting for its test) never ends unless the test releases it.
            assert pool.waitForDone(POOL_WAIT_MS), "work the test started on the thread pool did not end"
            QCoreApplication.processEvents()
            if pool.activeThreadCount() == 0:
                break
        else:
            pytest.fail("the test's work on the thread pool kept starting more work")
    finally:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
