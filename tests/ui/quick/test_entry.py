"""The entry point picks the window, and "Get it" opens the existing Programs page in a dark dialog."""

from __future__ import annotations

import sys
import threading

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.dependencies import service
from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.dependencies.specs import SPECS
from showrunner.ui import app as entry
from showrunner.ui.quick.programs_dialog import programs_dialog
from showrunner.ui.theme.tokens import ColorSet, ThemeColors, resolve


@pytest.mark.parametrize(("argv", "expected"), [(["showrunner"], "quick"), (["showrunner", "--widgets"], "widgets")])
def test_the_flag_picks_the_window(monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: str) -> None:
    ran: list[str] = []
    apis: list[object] = []
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(entry, "QApplication", lambda args: QApplication.instance())
    monkeypatch.setattr(entry.QQuickWindow, "setGraphicsApi", apis.append)
    monkeypatch.setattr(entry, "_run_quick", lambda app: ran.append("quick") or 0)
    monkeypatch.setattr(entry, "_run_widgets", lambda app, mode: ran.append("widgets") or 0)
    assert entry.main() == 0
    assert ran == [expected]
    assert apis == ([entry.QSGRendererInterface.GraphicsApi.OpenGL] if expected == "quick" else [])


def test_the_programs_dialog_lists_every_program_in_the_dark_theme(
    qapp: QApplication, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def check_all(_cancel: threading.Event | None = None) -> dict[str, DependencyStatus]:
        return {spec.id: DependencyStatus(spec.id, State.MISSING) for spec in SPECS}

    monkeypatch.setattr(service, "check_all", check_all)
    dialog, page = programs_dialog()
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: len(page.statuses) == len(SPECS))
    assert set(page.rows) == {spec.id for spec in SPECS}
    window = dialog.palette().color(QPalette.ColorRole.Window).name()
    assert window == resolve(ThemeColors(), ColorSet.DARK)["chrome"]
