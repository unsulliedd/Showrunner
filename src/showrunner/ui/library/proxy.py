"""Filtering the library tree by name and by what needs a look."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel

from showrunner.ui.library.model import DOT_ROLE


class LibraryFilter(QSortFilterProxyModel):
    """A row stays when its name, or the name of a row above it, contains the text; with "needs a look" on, only
    rows that carry a mark stay. A row that fails but has a row below it that passes stays too, so a match
    keeps its season and show."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._needs_look = False
        self.setRecursiveFilteringEnabled(True)

    @property
    def active(self) -> bool:
        return bool(self._text) or self._needs_look

    def set_text(self, text: str) -> None:
        self.beginFilterChange()
        self._text = text.strip().casefold()
        self.endFilterChange()

    def set_needs_look(self, enabled: bool) -> None:
        self.beginFilterChange()
        self._needs_look = enabled
        self.endFilterChange()

    def filterAcceptsRow(self, row: int, parent: QModelIndex | QPersistentModelIndex) -> bool:  # noqa: N802  # Qt's name
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        if self._needs_look and index.data(DOT_ROLE) not in ("failed", "needs_look"):
            return False
        if not self._text:
            return True
        node = index
        while node.isValid():
            if self._text in str(node.data()).casefold():
                return True
            node = node.parent()
        return False
