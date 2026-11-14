"""Status marks: one small dot per row, and the delegate that paints the library's summary and mark columns."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from showrunner.app.library.library import Mark
from showrunner.ui.library.model import DOT_ROLE, MARK_COLUMN, SUMMARY_COLUMN
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES

_MARK_ROLES = {Mark.UNSURE: "accent_ink", Mark.FAILED: "danger"}


def mark_color(theme: ThemeManager, mark: Mark) -> str | None:
    """The color of a mark in the active theme; None for no mark."""
    key = _MARK_ROLES.get(mark)
    return theme.roles[key] if key else None


def draw_dot(painter: QPainter, center_x: float, center_y: float, color: str) -> None:
    size = SIZES["mark_size"]
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(center_x - size / 2, center_y - size / 2, size, size))
    painter.restore()


def dot_icon(color: str) -> QIcon:
    """A dot on a transparent square, for a button that names a mark."""
    size = SIZES["mark_size"] * 2
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_dot(painter, size / 2, size / 2, color)
    painter.end()
    return QIcon(pixmap)


class MarkDot(QWidget):
    """A dot for use beside a text, in the color of a mark."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._mark = Mark.NONE
        self._role: str | None = None  # a color role that wins over the mark
        size = SIZES["mark_size"]
        self.setFixedSize(size, size)
        theme.changed.connect(self.update)

    def set_mark(self, mark: Mark) -> None:
        self._mark = mark
        self._role = None
        self.setVisible(mark is not Mark.NONE)
        self.update()

    def set_role(self, role: str | None) -> None:
        """Show the dot in a color role, such as `control` for changes planned; None hides it."""
        self._role = role
        self.setVisible(role is not None)
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802  # Qt's name
        color = self._theme.roles[self._role] if self._role else mark_color(self._theme, self._mark)
        if color:
            painter = QPainter(self)
            draw_dot(painter, self.width() / 2, self.height() / 2, color)
            painter.end()


class LibraryDelegate(QStyledItemDelegate):
    """Paints the summary in the muted color and the mark column as a dot.

    The row background, hover and selection are drawn by the style with the text left out, so a style sheet
    rule for the rows still applies; only the content is drawn here.
    """

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        if index.column() not in (SUMMARY_COLUMN, MARK_COLUMN):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDisplay
        style = opt.widget.style() if opt.widget else None
        if style is None:
            return
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        roles = self._theme.roles
        if index.column() == MARK_COLUMN:
            dot = index.data(DOT_ROLE)
            color = self._theme.roles[dot] if dot else None
            if color:
                rect: QRect = opt.rect
                draw_dot(painter, rect.center().x() + 0.5, rect.center().y() + 0.5, color)
            return
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setPen(QPen(QColor(roles["control_soft_ink" if selected else "muted"])))
        painter.setFont(opt.font)
        rect = opt.rect.adjusted(0, 0, -SIZES["space_sm"], 0)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:  # noqa: N802  # Qt's name
        hint = super().sizeHint(option, index)
        if index.column() == SUMMARY_COLUMN:
            hint.setWidth(hint.width() + SIZES["space_sm"])
        return hint
