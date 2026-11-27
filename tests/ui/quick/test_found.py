"""The programs the window checks: at startup, on a click or Refresh in the status bar, and the AI server again by
itself while it does not answer and when the app comes back to the front."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.ai import AiWatch
from showrunner.tools.ai.base import AiError, ErrorKind
from showrunner.ui.quick import found
from showrunner.ui.quick.window import WindowController

from .conftest import program_statuses
from .test_discard import _all, _click, _visible


def test_the_window_checks_tesseract_too_since_plans_need_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(found, "check", lambda spec, *args, **kwargs: spec.id)
    checked: dict[str, Any] = found.check_shown()
    assert "tesseract" in checked
    # The first-run screen still shows only the programs that read and write the files.
    assert found.SHOWN_PROGRAMS == ("mkvtoolnix", "ffmpeg")


class Server:
    """A stand-in AI server: answers with `models` while `running`, and counts how often it was asked."""

    name: ClassVar[str] = "ollama"

    def __init__(self) -> None:
        self.running = False
        self.models_installed: tuple[str, ...] = ("small:1b",)
        self.asked = 0

    def models(self) -> Sequence[str]:
        self.asked += 1
        if not self.running:
            raise AiError(ErrorKind.UNREACHABLE)
        return self.models_installed

    def version(self) -> str:
        return "1.0"


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Server:
    server = Server()
    monkeypatch.setattr(found, "AI", AiWatch(server))  # type: ignore[arg-type]
    monkeypatch.setattr(found, "load_settings", lambda: SimpleNamespace(value=SimpleNamespace(ai_model="small:1b")))
    return server


class Checks:
    """The programs' check, counted."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> dict[str, Any]:
        self.count += 1
        return program_statuses()


@pytest.fixture
def checks() -> Checks:
    return Checks()


@pytest.fixture
def controller(qapp: QApplication, server: Server, checks: Checks) -> Iterator[WindowController]:
    controller = WindowController(statuses=checks, get_program=lambda _: None)
    yield controller
    controller.deleteLater()


def states(controller: WindowController) -> list[tuple[str, str]]:
    return [(row["id"], row["state"]) for row in controller.status_programs]


def started(controller: WindowController, qtbot: QtBot) -> None:
    controller.start()
    qtbot.waitUntil(lambda: "checking" not in dict(states(controller)).values())


def test_the_status_bar_lists_every_program_the_plans_use_with_its_state(
    controller: WindowController, server: Server, qtbot: QtBot
) -> None:
    assert [state for _, state in states(controller)] == ["checking"] * 4
    started(controller, qtbot)
    assert states(controller) == [
        ("mkvtoolnix", "found"),
        ("ffmpeg", "missing"),
        ("tesseract", "missing"),
        ("ollama", "stopped"),
    ]
    rows = {row["id"]: row for row in controller.status_programs}
    assert rows["ollama"]["status"] == "Ollama is not running"
    assert rows["mkvtoolnix"]["tip"].startswith("Found at ")
    assert rows["tesseract"]["tip"] == "Reads picture subtitles (OCR)"
    server.running = True
    with qtbot.waitSignal(controller.programs_changed):
        controller.found.check_ai(now=True)
    rows = {row["id"]: row for row in controller.status_programs}
    assert (rows["ollama"]["state"], rows["ollama"]["status"], rows["ollama"]["found"]) == (
        "running",
        "Ollama · small:1b",
        True,
    )
    server.models_installed = ("other:2b",)
    with qtbot.waitSignal(controller.programs_changed):
        controller.found.check_ai(now=True)
    assert dict(states(controller))["ollama"] == "model_missing"


def test_a_change_of_the_ai_server_plans_the_places_again(
    controller: WindowController, server: Server, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    started(controller, qtbot)
    replans: list[bool] = []
    monkeypatch.setattr(controller.workspace, "replan", lambda: replans.append(True))
    server.running = True
    with qtbot.waitSignal(controller.found.ai_changed):
        controller.found.check_ai(now=True)
    assert replans


def test_the_ai_server_is_asked_again_by_itself_only_while_it_does_not_answer(
    controller: WindowController, server: Server, qtbot: QtBot
) -> None:
    started(controller, qtbot)
    retry = controller.found._ai_retry
    assert retry.isActive()
    assert retry.interval() == found.AI_RETRY_MS
    asked = server.asked
    retry.timeout.emit()
    qtbot.waitUntil(lambda: server.asked == asked + 1)
    server.running = True
    retry.timeout.emit()
    qtbot.waitUntil(lambda: dict(states(controller))["ollama"] == "running")
    asked = server.asked
    retry.timeout.emit()  # it answers now: not asked
    qtbot.wait(50)
    assert server.asked == asked


def test_the_ai_server_is_asked_again_when_the_app_comes_to_the_front(
    controller: WindowController, server: Server, qtbot: QtBot, qapp: QApplication
) -> None:
    started(controller, qtbot)
    server.running = True
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    qtbot.wait(50)
    assert dict(states(controller))["ollama"] == "stopped"
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    qtbot.waitUntil(lambda: dict(states(controller))["ollama"] == "running")


def test_a_click_on_the_programs_and_refresh_in_their_menu_check_them_all_again(
    controller: WindowController, server: Server, checks: Checks, qtbot: QtBot, load: Any
) -> None:
    started(controller, qtbot)
    load()
    window, root = load.window, load.window.contentItem()
    area = _visible(root, "programsArea")
    count, asked = checks.count, server.asked
    _click(window, area)
    qtbot.waitUntil(lambda: checks.count == count + 1 and server.asked == asked + 1)
    texts = [row.property("text") for row in found_texts(root)]
    assert "MKVToolNix 88.0" in texts
    assert "Ollama is not running" in texts
    _click(window, area, Qt.MouseButton.RightButton)
    menu = window.findChild(QObject, "programsMenu")
    qtbot.waitUntil(lambda: menu.property("visible"))
    menu.picked.emit("refresh")
    qtbot.waitUntil(lambda: checks.count == count + 2)
    assert not [w for w in load() if "StatusBar" in w]


def found_texts(root: Any) -> list[Any]:
    return [item for item in _all(root) if item.isVisible() and isinstance(item.property("text"), str)]
