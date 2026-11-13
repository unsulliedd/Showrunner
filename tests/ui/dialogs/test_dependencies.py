from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.app.dependencies import service
from showrunner.tools.dependencies.detect import DependencyStatus, Location, State
from showrunner.tools.dependencies.specs import SPECS
from showrunner.ui.dialogs.dependencies import DependenciesDialog
from showrunner.ui.i18n.catalog import STRINGS_DIR, tr
from showrunner.ui.main_window import MainWindow
from showrunner.ui.theme.manager import ThemeManager


def wait_until(condition: Callable[[], bool], seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture
def fake_statuses(monkeypatch: pytest.MonkeyPatch) -> dict[str, DependencyStatus]:
    statuses = {spec.id: DependencyStatus(spec.id, State.MISSING) for spec in SPECS}
    statuses["mkvtoolnix"] = DependencyStatus(
        "mkvtoolnix", State.FOUND, Path("C:/MKVToolNix/mkvmerge.exe"), Location.INSTALL_DIR, "103.0"
    )
    statuses["ffmpeg"] = DependencyStatus("ffmpeg", State.OUTDATED, Path("C:/ff/ffmpeg.exe"), Location.PATH, "4.4")
    # The page must not run the programs of the machine the tests run on.
    monkeypatch.setattr(service, "check_all", lambda cancel=None: dict(statuses))
    return statuses


def test_the_page_opens_headless_and_shows_every_program(
    qapp: QApplication, fake_statuses: dict[str, DependencyStatus]
) -> None:
    dialog = DependenciesDialog()
    dialog.show()
    wait_until(lambda: not dialog.busy)
    assert set(dialog.rows) == {spec.id for spec in SPECS}
    mkv = dialog.rows["mkvtoolnix"]
    assert mkv.state.text() == tr("dependencies.state.found")
    assert "103.0" in mkv.details.text()
    assert mkv.download.text() == tr("dependencies.update")
    ffmpeg = dialog.rows["ffmpeg"]
    assert ffmpeg.state.text() == tr("dependencies.state.outdated", version="6.0")
    assert ffmpeg.state.property("role") == "notice"
    tesseract = dialog.rows["tesseract"]
    assert tesseract.state.text() == tr("dependencies.state.missing")
    assert tesseract.download.text() == tr("dependencies.download")
    assert dialog.rows["llama_cpp"].download.menu() is not None
    assert dialog.recheck_button.isEnabled()
    dialog.close()


def test_strings_of_the_page_exist() -> None:
    strings = json.loads((STRINGS_DIR / "en.json").read_text(encoding="utf-8"))
    for spec in SPECS:
        assert spec.name_key in strings
        for feature in spec.features:
            assert f"feature.{feature.value}" in strings
        if len(spec.source.variants) > 1:
            for variant in spec.source.variants:
                assert f"dependencies.variant.{variant.id}" in strings
    for state in State:
        assert f"dependencies.state.{state.value}" in strings
    for location in Location:
        assert f"dependencies.location.{location.value}" in strings


def test_the_tools_menu_opens_the_page(
    qapp: QApplication, theme: ThemeManager, fake_statuses: dict[str, DependencyStatus], monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[DependenciesDialog] = []
    monkeypatch.setattr(DependenciesDialog, "exec", lambda self: opened.append(self) or 0)
    window = MainWindow(theme)
    window.dependencies_action.trigger()
    assert len(opened) == 1
    wait_until(lambda: not opened[0].busy)
    opened[0].close()
    window.close()
