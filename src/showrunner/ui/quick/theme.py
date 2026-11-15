"""The `Theme` object QML reads every color and size from, generated from the theme tokens.

Each Qt Quick role becomes a color property and each size an int property under the token's own name, so a QML file
writes `Theme.panel` or `Theme.space_md`. All properties share one notify signal: a new set of colors rebinds every
use at once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QColor

from showrunner.ui.theme.tokens import QUICK_FONT, QUICK_MONO, QUICK_ROLES, SIZES, ColorSet, ThemeColors, resolve


def _color(key: str) -> Callable[[Any], QColor]:
    return lambda self: QColor(self._roles[key])


def _size(key: str) -> Callable[[Any], int]:
    return lambda self: SIZES[key]


def _build() -> type[QObject]:
    changed = Signal()
    members: dict[str, object] = {"changed": changed}
    for key in QUICK_ROLES:
        members[key] = Property(QColor, _color(key), notify=changed)
    for key in SIZES:
        members[key] = Property(int, _size(key), notify=changed)
    members["font"] = Property(str, lambda _self: QUICK_FONT, constant=True)
    members["mono"] = Property(str, lambda _self: QUICK_MONO, constant=True)

    def __init__(self: Any, colors: ThemeColors | None = None, parent: QObject | None = None) -> None:  # noqa: N807
        QObject.__init__(self, parent)
        self.set_colors(colors or ThemeColors())

    def set_colors(self: Any, colors: ThemeColors) -> None:
        # Always the dark set: it is the one approved, and the light set has not been reviewed.
        self._roles = resolve(colors, ColorSet.DARK)
        self.changed.emit()

    members["__init__"] = __init__
    members["set_colors"] = set_colors
    members["__doc__"] = "Colors and sizes for QML, one property per token."
    # Signals and properties have to be in the class body when the class is made, so the class is made from them.
    return type("Theme", (QObject,), members)


Theme = _build()
