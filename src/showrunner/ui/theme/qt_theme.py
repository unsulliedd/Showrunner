"""Resolved theme tokens turned into what Qt draws with: a palette, a style sheet and the app font."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from string import Template

from PySide6.QtGui import QColor, QFont, QPalette

from showrunner.ui.theme.tokens import FONT_FAMILIES, SIZES

_TEMPLATE = Template((Path(__file__).parent / "style.qss").read_text(encoding="utf-8"))

_Role = QPalette.ColorRole

# Palette roles that native widgets read, filled from theme roles.
_PALETTE: dict[QPalette.ColorRole, str] = {
    _Role.Window: "chrome",
    _Role.WindowText: "ink",
    _Role.Base: "surface",
    _Role.AlternateBase: "chrome",
    _Role.Text: "ink",
    _Role.PlaceholderText: "muted",
    _Role.Button: "chrome_2",
    _Role.ButtonText: "ink",
    _Role.BrightText: "danger",
    _Role.Highlight: "select",
    _Role.HighlightedText: "ink",
    _Role.Link: "link",
    _Role.LinkVisited: "link",
    _Role.ToolTipBase: "tip",
    _Role.ToolTipText: "tip_ink",
    _Role.Accent: "control",
    _Role.Light: "surface",
    _Role.Midlight: "line",
    _Role.Mid: "line_strong",
    _Role.Dark: "line_strong",
    _Role.Shadow: "muted",
}
_DISABLED: dict[QPalette.ColorRole, str] = {
    _Role.WindowText: "muted",
    _Role.Text: "muted",
    _Role.ButtonText: "muted",
}


def build_palette(roles: Mapping[str, str]) -> QPalette:
    palette = QPalette()
    for qt_role, key in _PALETTE.items():
        palette.setColor(qt_role, QColor(roles[key]))
    for qt_role, key in _DISABLED.items():
        palette.setColor(QPalette.ColorGroup.Disabled, qt_role, QColor(roles[key]))
    return palette


def build_stylesheet(roles: Mapping[str, str]) -> str:
    """The style sheet with every `$name` filled in. An unknown name raises KeyError."""
    return _TEMPLATE.substitute({**SIZES, **roles})


def build_font() -> QFont:
    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(SIZES["text_md"])
    return font
