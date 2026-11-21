"""The entry point opens the Qt Quick window on OpenGL; there is no other window to pick."""

from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.ui import app as entry


def test_the_window_asks_for_opengl_before_it_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(sys, "argv", ["showrunner"])
    monkeypatch.setattr(entry, "QApplication", lambda args: calls.append(args) or QApplication.instance())
    monkeypatch.setattr(entry.QQuickWindow, "setGraphicsApi", calls.append)
    monkeypatch.setattr(entry, "collect_on_gui_thread", lambda app: calls.append("collector"))
    monkeypatch.setattr(entry, "build_engine", lambda controller: calls.append("engine") or _NoWindow())
    assert entry.main() == 1
    assert calls == [entry.QSGRendererInterface.GraphicsApi.OpenGL, ["showrunner"], "collector", "engine"]


def test_the_window_has_the_app_icon_and_the_process_its_own_app_id(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance()
    ids: list[str] = []
    monkeypatch.setattr(sys, "argv", ["showrunner"])
    monkeypatch.setattr(entry, "QApplication", lambda args: app)
    monkeypatch.setattr(entry, "_set_taskbar_identity", lambda: ids.append("set"))
    monkeypatch.setattr(entry, "collect_on_gui_thread", lambda app: None)
    monkeypatch.setattr(entry, "build_engine", lambda controller: _NoWindow())
    assert entry.main() == 1
    assert entry.ICON.is_file()
    assert not app.windowIcon().isNull()
    assert 256 in [size.width() for size in app.windowIcon().availableSizes()]
    assert ids == ["set"]


class _NoWindow:
    @staticmethod
    def rootObjects() -> list[object]:  # noqa: N802  # Qt's name
        return []
