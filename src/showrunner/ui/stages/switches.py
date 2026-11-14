"""A stage's switch in the toolbar: the main part turns the stage on or off, the arrow opens its few plain options."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QStyle, QStyleOptionButton, QToolButton, QWidget

from showrunner.ui.library.marks import draw_dot
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES


class StageSwitch(QToolButton):
    """The check box is the icon, with an On and an Off pixmap, so Qt swaps it with the checked state; a blocked
    stage carries a `danger` dot beside it."""

    def __init__(self, stage_id: str, name: str, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stage_id = stage_id
        self._name = name
        self._theme = theme
        self._blocked = False
        self.setProperty("role", "stage")
        self.setCheckable(True)
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
        box = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
        dot = SIZES["mark_size"] + SIZES["space_sm"] if self._blocked else 0
        ratio = self.devicePixelRatioF()
        icon = QIcon()
        for state, on in ((QIcon.State.On, True), (QIcon.State.Off, False)):
            pixmap = QPixmap(QSize(box + dot, box) * ratio)
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            option = QStyleOptionButton()
            option.rect = QRect(0, 0, box, box)
            option.palette = self.palette()
            option.state = QStyle.StateFlag.State_Enabled | (
                QStyle.StateFlag.State_On if on else QStyle.StateFlag.State_Off
            )
            self.style().drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, option, painter, self)
            if self._blocked:
                draw_dot(painter, box + dot / 2 + SIZES["space_xs"], box / 2, self._theme.roles["danger"])
            painter.end()
            icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
        self.setIconSize(QSize(box + dot, box))
        self.setIcon(icon)
