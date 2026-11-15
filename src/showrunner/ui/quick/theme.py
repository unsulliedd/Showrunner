"""The `Theme` object QML reads every color and size from, generated from the theme tokens.

Each Qt Quick role becomes a color property and each size an int property under the token's own name, so a QML file
writes `Theme.panel` or `Theme.space_md`. All properties share one notify signal: a new set of colors or sizes
rebinds every use at once. What the values are (theme mode, colour changes, density) is decided by `Look`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QColor

from showrunner.ui.theme.tokens import QUICK_FONT, QUICK_MONO, QUICK_ROLES, SIZES, ColorSet, ThemeColors, resolve


def _color(key: str) -> Callable[[Any], QColor]:
    return lambda self: QColor(self._roles[key])


def _size(key: str) -> Callable[[Any], int]:
    return lambda self: self._sizes[key]


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
        self._sizes = dict(SIZES)
        self.set_colors(colors or ThemeColors())

    def set_colors(self: Any, colors: ThemeColors, color_set: ColorSet = ColorSet.DARK) -> None:
        self.show(resolve(colors, color_set), self._sizes)

    def show(self: Any, roles: Mapping[str, str], sizes: Mapping[str, int]) -> None:
        self._roles = dict(roles)
        self._sizes = dict(sizes)
        self.changed.emit()

    def follow(self: Any, look: Any) -> None:
        """Show `look` now and after each of its changes. The connection is to this object's own method, so it ends
        with the engine that owns it."""
        self._look = look
        look.changed.connect(self.refresh)
        self.refresh()

    def refresh(self: Any) -> None:
        self.show(self._look.roles, self._look.sizes)

    members["__init__"] = __init__
    members["set_colors"] = set_colors
    members["show"] = show
    members["follow"] = follow
    members["refresh"] = refresh
    members["__doc__"] = "Colors and sizes for QML, one property per token."
    # Signals and properties have to be in the class body when the class is made, so the class is made from them.
    return type("Theme", (QObject,), members)


Theme = _build()
