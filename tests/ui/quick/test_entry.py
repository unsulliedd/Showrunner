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
    monkeypatch.setattr(entry, "build_engine", lambda controller: calls.append("engine") or _NoWindow())
    assert entry.main() == 1
    assert calls == [entry.QSGRendererInterface.GraphicsApi.OpenGL, ["showrunner"], "engine"]


class _NoWindow:
    @staticmethod
    def rootObjects() -> list[object]:  # noqa: N802  # Qt's name
        return []
