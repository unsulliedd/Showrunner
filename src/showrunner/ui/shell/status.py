"""The status bar's parts: the library summary and the progress of a running job."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QWidget

from showrunner.app.library.library import Counts
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.sheet.format import count_parts
from showrunner.ui.theme.tokens import SIZES


def _label(text: str, role: str = "") -> QLabel:
    label = QLabel(text)
    # Labels are drawn in the ink color unless they carry a role.
    label.setProperty("role", role or "muted")
    return label


class SummaryBar(QWidget):
    """ "299 videos · 2 shows, 296 episodes · 5 unsure pairings", with each problem in its mark's color."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(SIZES["space_md"])
        self.set_counts(None)

    def set_counts(self, counts: Counts | None) -> None:
        """Show the counts of a library, or "no library" for None."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        if counts is None or counts.videos == 0:
            self._layout.addWidget(_label(tr("status.empty")))
        else:
            for number, (text, role) in enumerate(count_parts(counts)):
                prefix = tr("status.separator") + " " if number else ""
                self._layout.addWidget(_label(prefix + text, role))
        self._layout.addStretch()

    def texts(self) -> list[str]:
        return [
            self._layout.itemAt(i).widget().text()
            for i in range(self._layout.count())
            if self._layout.itemAt(i).widget()
        ]


class JobBar(QWidget):
    """What a running job reports: a label, a progress bar and Cancel. Hidden while no job runs."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES["space_md"])
        self.label = QLabel()
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(SIZES["progress_width"])
        self.cancel = QPushButton(tr("common.cancel"))
        self.cancel.setFlat(True)
        self.cancel.clicked.connect(self.cancel_requested)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        layout.addWidget(self.cancel)
        self.hide()

    def start(self, text: str) -> None:
        """Show the bar as busy, without a count yet."""
        self.label.setText(text)
        self.bar.setRange(0, 0)
        self.cancel.setEnabled(True)
        self.show()

    def report(self, text: str, done: int, total: int) -> None:
        self.label.setText(text)
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)

    def cancelling(self, text: str) -> None:
        self.label.setText(text)
        self.cancel.setEnabled(False)
