"""Small widgets shared by the sheet's sections."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTreeView,
    QWidget,
)

from showrunner.ui.theme.tokens import SIZES


class ElidedLabel(QLabel):
    """A label that cuts its text in the middle to fit, and shows all of it as a tooltip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        # Without this the label would ask for its whole text as width and widen the window.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  # Qt's name
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, self.width()))


def heading(text: str, count: int | None = None) -> QWidget:
    """A section heading with its count in the muted color."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SIZES["space_md"])
    title = QLabel(text)
    title.setProperty("heading", True)
    layout.addWidget(title)
    if count is not None:
        number = QLabel(str(count))
        number.setProperty("role", "muted")
        layout.addWidget(number)
    layout.addStretch()
    return row


class FitTreeView(QTreeView):
    """A tree that is as tall as its rows, for the sections of a page that scrolls as a whole."""

    def __init__(self, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", role)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setItemsExpandable(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformRowHeights(True)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  # Qt's name
        super().showEvent(event)
        # Before the first show a row is shorter than it is drawn, by what the style sheet adds around it.
        self.fit()

    def fit(self) -> None:
        """Set the height to the header and every row, which the caller has expanded."""
        model = self.model()
        # Row heights come from the style sheet, which applies once the widget is polished.
        self.ensurePolished()

        def rows(parent: QModelIndex) -> int:
            total = 0
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                total += self.rowHeight(index) + rows(index)
            return total

        self.setFixedHeight(self.header().sizeHint().height() + rows(QModelIndex()))


def replace_content(area: QScrollArea, content: QWidget) -> None:
    """Put new content into a scroll area. The old content is deleted later, not now: a button that was clicked
    in it may still be running its slot."""
    old = area.takeWidget()
    if old is not None:
        old.hide()
        old.deleteLater()
    area.setWidget(content)
