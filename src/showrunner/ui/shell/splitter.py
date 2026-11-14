"""A splitter that restores saved sizes once it has its real width."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QSplitter, QWidget


class SavedSplitter(QSplitter):
    """Sizes set while the splitter is hidden are scaled to whatever width it had then, so a saved size
    is applied at the first show, when the width is the one the user sees."""

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._pending: list[int] = []
        self._pending_is_default = False
        self._shown = False

    def restore(self, sizes: list[int], *, default: bool = False) -> None:
        """Apply sizes at the first show. `default` marks sizes the user did not choose: they are not saved."""
        if self._shown:
            self.setSizes(sizes)
        else:
            self._pending = list(sizes)
            self._pending_is_default = default

    def saved_sizes(self) -> list[int]:
        """The sizes to save: the user's, or the ones restored and not yet applied; empty when neither exists."""
        if self._pending:
            return [] if self._pending_is_default else self._pending
        return self.sizes() if self._shown else []

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  # Qt's name
        super().showEvent(event)
        if not self._shown:
            self._shown = True
            if self._pending:
                self.setSizes(self._pending)
                self._pending = []
