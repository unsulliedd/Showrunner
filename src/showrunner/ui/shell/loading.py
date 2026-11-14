"""The loading state: shown in place of the empty state while the first library is read."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QHideEvent, QPainter, QPaintEvent, QPalette, QPen, QShowEvent
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from showrunner.ui.i18n.catalog import tr
from showrunner.ui.theme.tokens import SIZES

_STEP_DEGREES = 30
_STEP_MS = 80
_ARC_DEGREES = 270


class Spinner(QWidget):
    """A rotating arc in the palette's accent colour. It turns only while visible, so a hidden one costs nothing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(SIZES["spinner"], SIZES["spinner"])
        self.angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(_STEP_MS)
        self._timer.timeout.connect(self._turn)

    @property
    def spinning(self) -> bool:
        return self._timer.isActive()

    def _turn(self) -> None:
        self.angle = (self.angle + _STEP_DEGREES) % 360
        self.update()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  # Qt's name
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802  # Qt's name
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802  # Qt's name
        width = max(2, SIZES["spinner"] // 8)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().color(QPalette.ColorRole.Accent), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        inset = width / 2
        # Qt measures arcs in sixteenths of a degree, counter-clockwise from three o'clock.
        painter.drawArc(
            QRectF(inset, inset, self.width() - width, self.height() - width),
            -self.angle * 16,
            _ARC_DEGREES * 16,
        )


class LoadingView(QFrame):
    """A spinner, a title and the progress of the running load, centred on the sheet."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "page")
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        block = QWidget()
        block.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES["space_lg"])
        self.spinner = Spinner()
        layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel(tr("loading.title"))
        self.title.setProperty("text_size", "xl")
        layout.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        self.detail = QLabel()
        self.detail.setProperty("role", "muted")
        layout.addWidget(self.detail, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(block, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def set_detail(self, text: str) -> None:
        self.detail.setText(text)
