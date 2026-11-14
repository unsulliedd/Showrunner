"""The library panel: the name filter, the "needs a look" button and the tree."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.library.library import Mark
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.marks import LibraryDelegate, dot_icon, mark_color
from showrunner.ui.library.model import MARK_COLUMN, NAME_COLUMN, SUMMARY_COLUMN, LibraryModel
from showrunner.ui.library.proxy import LibraryFilter
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES


class LibraryPanel(QWidget):
    # The row now current, as an index of the model; invalid when nothing is selected.
    selection_changed = Signal(QModelIndex)

    def __init__(self, model: LibraryModel, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._theme = theme
        self.proxy = LibraryFilter(self)
        self.proxy.setSourceModel(model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SIZES["space_md"], 0, 0, 0)
        layout.setSpacing(SIZES["space_md"])

        filters = QHBoxLayout()
        filters.setSpacing(SIZES["space_md"])
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(tr("library.filter"))
        self.filter_edit.setClearButtonEnabled(True)
        # A line edit takes dropped text, which would swallow a file dropped onto it.
        self.filter_edit.setAcceptDrops(False)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        self.needs_look = QPushButton()
        self.needs_look.setCheckable(True)
        self.needs_look.toggled.connect(self._on_filter_changed)
        filters.addWidget(self.filter_edit, 1)
        filters.addWidget(self.needs_look)
        layout.addLayout(filters)

        self.tree = QTreeView()
        self.tree.setProperty("role", "library")
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setIndentation(SIZES["space_xl"])
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setItemDelegate(LibraryDelegate(theme, self.tree))
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(SUMMARY_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(MARK_COLUMN, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(MARK_COLUMN, SIZES["mark_size"] + 2 * SIZES["space_md"])
        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        layout.addWidget(self.tree, 1)

        model.library_changed.connect(self._update_count)
        model.marks_changed.connect(self._update_count)
        theme.changed.connect(self._update_icon)
        self._update_count()
        self._update_icon()

    @property
    def visible_rows(self) -> int:
        """Rows now shown, expanded or not."""

        def count(parent: QModelIndex) -> int:
            return sum(1 + count(self.proxy.index(r, 0, parent)) for r in range(self.proxy.rowCount(parent)))

        return count(QModelIndex())

    def current_source_index(self) -> QModelIndex:
        return self.proxy.mapToSource(self.tree.currentIndex())

    def select(self, source_index: QModelIndex) -> None:
        """Make a row current and show it, whatever it is nested in."""
        index = self.proxy.mapFromSource(source_index)
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)

    def expand_default(self) -> None:
        """Shows open, seasons closed, except the season that holds the first video that needs a look."""
        self.tree.collapseAll()
        for row in range(self.proxy.rowCount()):
            self.tree.expand(self.proxy.index(row, 0))
        marked = self._model.first_marked()
        index = self.proxy.mapFromSource(marked)
        while index.isValid():
            self.tree.expand(index)
            index = index.parent()

    def _on_filter_changed(self, *_args: object) -> None:
        was_active = self.proxy.active
        self.proxy.set_text(self.filter_edit.text())
        self.proxy.set_needs_look(self.needs_look.isChecked())
        if self.proxy.active:
            self.tree.expandAll()
        elif was_active:
            self.expand_default()

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self.selection_changed.emit(self.proxy.mapToSource(current))

    def _update_count(self) -> None:
        self.needs_look.setText(tr("library.needs_look", count=self._model.needs_look_count()))

    def _update_icon(self) -> None:
        color = mark_color(self._theme, Mark.UNSURE)
        if color:
            self.needs_look.setIcon(dot_icon(color))
