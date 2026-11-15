"""A stage's button in the toolbar: it shows the stage's count or why it cannot run, the arrow opens its few plain
options."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from showrunner.ui.library.marks import draw_dot
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES


class StageSwitch(QToolButton):
    """A blocked stage carries a `danger` dot as its icon."""

    def __init__(self, stage_id: str, name: str, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stage_id = stage_id
        self._name = name
        self._theme = theme
        self._blocked = False
        self.setProperty("role", "stage")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setMenu(QMenu(self))
        self.setText(name)
        theme.changed.connect(self._paint_icon)
        self._paint_icon()

    def show_state(self, *, count: int | None, blocked: str = "", missing: str = "") -> None:
        """`count` of the files the stage changes after a preview, None before one; `blocked` why its options
        stop it; `missing` the program it needs and lacks."""
        self.setEnabled(not missing)
        self._blocked = bool(blocked) and not missing
        shown = "" if count is None or self._blocked else f"  {count}"
        self.setText(self._name + shown)
        self.setToolTip(missing or blocked)
        self._paint_icon()

    def _paint_icon(self) -> None:
        if not self._blocked:
            self.setIcon(QIcon())
            return
        size = SIZES["mark_size"] + SIZES["space_sm"]
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(QSize(size, size) * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        draw_dot(painter, size / 2, size / 2, self._theme.roles["danger"])
        painter.end()
        self.setIconSize(QSize(size, size))
        self.setIcon(QIcon(pixmap))
