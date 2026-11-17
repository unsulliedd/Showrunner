from __future__ import annotations

import threading

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QThreadPool
from pytestqt.qtbot import QtBot
from shiboken6 import isValid

from showrunner.ui.quick.plans import LivePlanner


def test_a_plan_job_lives_until_its_pool_thread_has_left_the_emit(qtbot: QtBot) -> None:
    # A job freed while its pool thread is still inside `finished.emit` makes that thread read freed memory.
    planner = LivePlanner()
    planned: list[object] = []
    planner.planned.connect(lambda _token, result: planned.append(result))
    gate, inside, release = threading.Event(), threading.Event(), threading.Event()
    planner.request(1, lambda: gate.wait(5) and "plan")
    job = planner._job
    assert job is not None

    def hold(_result: object) -> None:  # runs on the pool thread, inside the emit
        inside.set()
        release.wait(5)

    job.finished.connect(hold, Qt.ConnectionType.DirectConnection)
    gate.set()
    try:
        assert inside.wait(5)
        qtbot.waitUntil(lambda: planned == ["plan"])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert isValid(job)
    finally:
        release.set()
    assert QThreadPool.globalInstance().waitForDone(5000)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(job)  # and once it has, the job is gone
