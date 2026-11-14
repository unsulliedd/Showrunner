from __future__ import annotations

import logging

import pytest
from PySide6.QtWidgets import QApplication

from showrunner.app.settings.app_settings import ThemeMode
from showrunner.ui.settings.appearance import AppearancePage as AppearanceDialog
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import DEFAULT_BASES, Base, ThemeColors, with_base


def test_dialog_opens_with_every_string_found(
    qapp: QApplication, theme: ThemeManager, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="showrunner.ui.i18n"):
        dialog = AppearanceDialog(theme)
        dialog.show()
    assert dialog.isVisible()
    assert caplog.records == []
    dialog.close()


def test_mode_box_and_resets_drive_the_theme(qapp: QApplication, theme: ThemeManager) -> None:
    theme.set_colors(with_base(ThemeColors(), Base.ACCENT, "#123456"))
    dialog = AppearanceDialog(theme)
    assert dialog._swatches[Base.ACCENT].text() == "#123456"
    assert dialog._resets[Base.ACCENT].isEnabled()
    assert not dialog._resets[Base.PRIMARY].isEnabled()

    dialog._resets[Base.ACCENT].click()
    assert theme.colors == ThemeColors()
    assert dialog._swatches[Base.ACCENT].text() == DEFAULT_BASES[Base.ACCENT]

    dialog._mode.setCurrentIndex(dialog._mode.findData(ThemeMode.DARK))
    assert theme.mode is ThemeMode.DARK
