from __future__ import annotations

import gc
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, QTimer

from showrunner.app.storage.paths import HOME_ENV_VAR

POOL_WAIT_MS = 10_000
# Each round delivers what the pool's work sent back, which may start more work (a plan after a program check).
POOL_ROUNDS = 10
COLLECT_MS = 50
FULL_EVERY = 50  # tests between full collections
_FINISHED = [0]


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


@pytest.fixture(scope="session", autouse=True)
def collected_on_the_main_thread(qapp: QCoreApplication) -> Iterator[None]:
    """Python's collector runs on whichever thread allocates enough, a pool thread included. A pool-thread collection
    while the main thread was inside Qt crashed the process with an access violation under load, also with nothing of
    Qt's to free. So automatic collection is off, and a timer on the main thread collects whenever the counts pass
    the collector's own thresholds, at each turn of the event loop."""

    def collect() -> None:
        young, middle, _old = gc.get_count()
        first, second, _third = gc.get_threshold()
        if young > first:
            gc.collect(1 if middle > second else 0)

    gc.disable()
    timer = QTimer()
    timer.setInterval(COLLECT_MS)
    timer.timeout.connect(collect)
    timer.start()
    yield
    timer.stop()
    gc.enable()


def pytest_runtest_logfinish(nodeid: str, location: tuple[str, int | None, str]) -> None:
    """Now and then a full collection on the main thread, once pytest has let go of the test's fixture values.

    Qt deletes a window's objects at the end of its test, but their Python wrappers stay in reference cycles (a child
    holding a bound method of its controller), most of them old by then; only a full collection frees those. One
    after every test doubled the suite's time, as it walks everything the session holds."""
    _FINISHED[0] += 1
    if _FINISHED[0] % FULL_EVERY == 0:
        gc.collect()
