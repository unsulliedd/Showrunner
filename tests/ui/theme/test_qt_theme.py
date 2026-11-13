from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from showrunner.app.settings.app_settings import ThemeMode, load_settings
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.qt_theme import build_palette, build_stylesheet
from showrunner.ui.theme.tokens import Base, ColorSet, ThemeColors, resolve, with_base


@pytest.mark.parametrize("color_set", list(ColorSet))
def test_stylesheet_has_no_unresolved_token(color_set: ColorSet) -> None:
    sheet = build_stylesheet(resolve(ThemeColors(), color_set))
    assert "$" not in sheet
    assert resolve(ThemeColors(), color_set)["control_fill"] in sheet


def test_palette_uses_the_roles() -> None:
    roles = resolve(ThemeColors(), ColorSet.DARK)
    palette = build_palette(roles)
    assert palette.color(QPalette.ColorRole.Base).name() == roles["surface"]
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == roles["muted"]


def test_mode_picks_the_color_set_and_is_saved(theme: ThemeManager, qapp: QApplication) -> None:
    assert theme.color_set is ColorSet.LIGHT
    theme.set_mode(ThemeMode.DARK)
    assert theme.color_set is ColorSet.DARK
    assert qapp.palette().color(QPalette.ColorRole.Base).name() == resolve(ThemeColors(), ColorSet.DARK)["surface"]
    assert load_settings().value.theme_mode is ThemeMode.DARK


def test_system_change_reapplies_only_in_system_mode(theme: ThemeManager, qapp: QApplication) -> None:
    applied: list[None] = []
    theme.changed.connect(lambda: applied.append(None))
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert applied == []
    theme.set_mode(ThemeMode.SYSTEM)
    applied.clear()
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
    assert applied == [None]


def test_color_changes_apply_and_are_saved(theme: ThemeManager, qapp: QApplication, data_home: Path) -> None:
    theme.set_colors(with_base(ThemeColors(), Base.PRIMARY, "#7a1f1f"))
    assert "#7a1f1f" in qapp.styleSheet()
    saved = json.loads((data_home / "theme.json").read_text(encoding="utf-8"))
    assert saved["base"] == {"primary": "#7a1f1f"}
