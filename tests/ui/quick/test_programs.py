"""Settings → Programs: checks on a pool thread, a download only after a yes, an installer only after a second yes,
Cancel, and "Get it" opening the section on its program."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.dependencies import service
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.dependencies.install import Asset, DownloadPlan, InstallCancelledError
from showrunner.tools.dependencies.specs import SPEC_BY_ID, SPECS, Archive
from showrunner.ui.quick.programs import Programs, row
from showrunner.ui.quick.window import WindowController


@pytest.fixture
def statuses(monkeypatch: pytest.MonkeyPatch) -> dict[str, DependencyStatus]:
    found = {spec.id: DependencyStatus(spec.id, State.MISSING) for spec in SPECS}
    monkeypatch.setattr(service, "check_all", lambda cancel=None: dict(found))
    monkeypatch.setattr(service, "check", lambda spec, cancel=None: found[spec.id])
    return found


def test_a_row_says_the_state_the_version_and_what_it_turns_on() -> None:
    spec = SPEC_BY_ID["mkvtoolnix"]
    found = row(spec, DependencyStatus(spec.id, State.FOUND, Path("tools") / "mkvmerge", version="88.0"), False)
    assert found["state"] == "Found"
    assert found["tone"] == "add"
    assert found["details"] == ["Version 88.0", str(Path("tools") / "mkvmerge")]
    assert found["download"] == "Update"
    assert found["unlocks"].startswith("Turns on: ")
    checking = row(spec, None, False)
    assert checking["state"] == "Checking…"
    assert checking["download"] == "Download"


def test_the_first_show_checks_every_program_once(
    qapp: QApplication, qtbot: QtBot, statuses: dict[str, DependencyStatus]
) -> None:
    programs = Programs()
    with qtbot.waitSignal(programs.statuses_changed):
        programs.show("ffmpeg")
    qtbot.waitUntil(lambda: not programs.busy)
    assert programs.focus == "ffmpeg"
    assert [r["id"] for r in programs.rows] == [spec.id for spec in SPECS]
    programs.show()
    assert not programs.busy


def test_a_download_waits_for_a_yes(
    qapp: QApplication, qtbot: QtBot, statuses: dict[str, DependencyStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    installed: list[str] = []
    monkeypatch.setattr(service, "plan_download", lambda spec_id, variant=None: _plan(spec_id, Archive.ZIP))

    def install(plan: Any, progress: Any, cancel: threading.Event) -> DependencyStatus:
        progress(1_000_000, 2_000_000)
        installed.append(plan.spec_id)
        return DependencyStatus(plan.spec_id, State.FOUND, Path("tools") / "ffmpeg", version="7.1")

    monkeypatch.setattr(service, "install", install)
    programs = Programs()
    programs.download("ffmpeg", "")
    qtbot.waitUntil(lambda: bool(programs.question))
    assert "example.org" in programs.question["text"]
    programs.answer(False)
    assert installed == []
    assert not programs.question
    programs.download("ffmpeg", "")
    qtbot.waitUntil(lambda: bool(programs.question))
    with qtbot.waitSignal(programs.statuses_changed):
        programs.answer(True)
    qtbot.waitUntil(lambda: not programs.busy)
    assert installed == ["ffmpeg"]
    assert programs.tone == "add"
    assert "7.1" in programs.message


def test_an_installer_starts_only_after_a_second_yes(
    qapp: QApplication, qtbot: QtBot, statuses: dict[str, DependencyStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Path] = []
    monkeypatch.setattr(service, "plan_download", lambda spec_id, variant=None: _plan(spec_id, Archive.INSTALLER))
    monkeypatch.setattr(service, "download_installer", lambda plan, progress, cancel: Path("setup.exe"))
    monkeypatch.setattr(service, "start_installer", started.append)
    programs = Programs()
    programs.download("tesseract", "")
    qtbot.waitUntil(lambda: bool(programs.question))
    programs.answer(True)
    qtbot.waitUntil(lambda: bool(programs.question) and "installer" in programs.question["title"].lower())
    assert started == []
    programs.answer(False)
    assert started == []
    assert "setup.exe" in programs.message
    programs.download("tesseract", "")
    qtbot.waitUntil(lambda: bool(programs.question))
    programs.answer(True)
    qtbot.waitUntil(lambda: bool(programs.question) and "installer" in programs.question["title"].lower())
    programs.answer(True)
    assert started == [Path("setup.exe")]


def test_cancel_stops_a_download_and_nothing_changes(
    qapp: QApplication, qtbot: QtBot, statuses: dict[str, DependencyStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "plan_download", lambda spec_id, variant=None: _plan(spec_id, Archive.ZIP))

    def install(plan: Any, progress: Any, cancel: threading.Event) -> DependencyStatus:
        assert cancel.wait(5)
        raise InstallCancelledError()

    monkeypatch.setattr(service, "install", install)
    programs = Programs()
    programs.download("ffmpeg", "")
    qtbot.waitUntil(lambda: bool(programs.question))
    programs.answer(True)
    assert programs.cancellable
    programs.cancel()
    qtbot.waitUntil(lambda: not programs.busy)
    assert programs.message == "Cancelled. Nothing was changed."


def test_get_it_opens_settings_on_the_program(
    qapp: QApplication, qtbot: QtBot, statuses: dict[str, DependencyStatus]
) -> None:
    controller = WindowController(statuses=lambda: {})
    with qtbot.waitSignal(controller.settings.open_asked) as opened:
        controller.get_program("mkvtoolnix")
    assert opened.args == ["programs"]
    assert controller.settings.programs.focus == "mkvtoolnix"
    qtbot.waitUntil(lambda: not controller.settings.programs.busy)
    controller.deleteLater()


def _plan(spec_id: str, archive: Archive) -> DownloadPlan:
    variant = replace(SPEC_BY_ID[spec_id].source.variants[0], archive=archive)
    return DownloadPlan(spec_id, variant, "1.0", (Asset("https://example.org/tool", "tool", 2_000_000, None),))


def test_closing_during_the_first_check_keeps_it_and_a_question_is_a_no(
    qapp: QApplication, qtbot: QtBot, statuses: dict[str, DependencyStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    programs = Programs()
    programs.show()
    programs.stop()  # Settings closed while the check runs: the check goes on
    qtbot.waitUntil(lambda: not programs.busy)
    assert programs.statuses == statuses
    monkeypatch.setattr(service, "plan_download", lambda spec_id, variant=None: _plan(spec_id, Archive.ZIP))
    programs.download("ffmpeg", "")
    qtbot.waitUntil(lambda: bool(programs.question))
    programs.stop()
    assert not programs.question


def test_a_check_that_ends_after_its_window_is_gone_reaches_nothing(qapp: QApplication, qtbot: QtBot) -> None:
    release = threading.Event()
    checked = threading.Event()

    def slow_check() -> dict[str, DependencyStatus]:
        checked.set()
        release.wait(10)
        return {}

    controller = WindowController(statuses=slow_check)
    controller.start()
    assert checked.wait(10)
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    release.set()
    assert QThreadPool.globalInstance().waitForDone(10_000)
    # The result would call into the deleted window; pytest-qt fails the test on an exception in a slot.
    qtbot.wait(50)
