from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from showrunner.app.settings.app_settings import ThemeMode
from showrunner.app.storage.paths import HOME_ENV_VAR
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import ThemeColors


@pytest.fixture(autouse=True)
def data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Widgets save settings and the theme as the user changes them; tests must never touch the real data folder.
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    return tmp_path


@pytest.fixture
def theme(qapp: QApplication) -> ThemeManager:
    return ThemeManager(ThemeMode.LIGHT, ThemeColors())


@pytest.fixture(autouse=True)
def delete_windows(qapp: QApplication) -> Iterator[None]:
    """Every window a test opened goes with it: a live window is restyled each time a later test applies a theme."""
    yield
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
