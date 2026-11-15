"""The library tree as QML's `TreeView` reads it: one column, with named roles for what a row draws."""

from __future__ import annotations

from collections.abc import Iterator

from PySide6.QtCore import QByteArray, QModelIndex, QPersistentModelIndex, Qt

from showrunner.app.library.library import Mark
from showrunner.core.media import Episode
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.model import DOT_ROLE, MARK_ROLE, NAME_COLUMN, SUMMARY_COLUMN, Kind, LibraryModel
from showrunner.ui.library.proxy import LibraryFilter

_FIRST = Qt.ItemDataRole.UserRole + 100
KIND, LABEL, NUMBER, SUMMARY, PROBLEM, PLANNED, ROW_ID = range(_FIRST, _FIRST + 7)
ROLE_NAMES = {
    KIND: "kind",
    LABEL: "label",
    NUMBER: "number",  # an episode's number, drawn apart from its title
    SUMMARY: "summary",  # a group's count of videos, a video's subtitle languages
    PROBLEM: "problem",  # a video that needs a look: the theme role its mark is drawn in, else ""
    PLANNED: "planned",  # a planned change at or below the row
    ROW_ID: "row_id",  # a video's path, a group's place in the tree
}
_PROBLEM_ROLES = {Mark.FAILED: "drop", Mark.UNSURE: "change"}

type Index = QModelIndex | QPersistentModelIndex


class LibraryTree(LibraryFilter):
    """The name column of a `LibraryModel`, filtered, with the summary and marks folded in as roles."""

    def source(self) -> LibraryModel:
        model = self.sourceModel()
        assert isinstance(model, LibraryModel)
        return model

    def filterAcceptsColumn(self, column: int, parent: Index) -> bool:  # noqa: N802  # Qt's name
        return column == NAME_COLUMN

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802  # Qt's name
        return {**super().roleNames(), **{role: QByteArray(name.encode()) for role, name in ROLE_NAMES.items()}}

    def row_id(self, index: Index) -> str:
        """A video's path; for a group, the names of the rows down to it, so it stays the same across a reload."""
        source = self.mapToSource(index)
        path = self.source().path(source)
        if path is not None:
            return str(path)
        names = []
        while source.isValid():
            names.append(f"{self.source().kind(source)}:{source.data()}")
            source = source.parent()
        return "/".join(reversed(names))

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if role not in ROLE_NAMES:
            return super().data(index, role)
        model = self.source()
        source = self.mapToSource(index)
        kind = model.kind(source)
        if role == KIND:
            return kind.value
        if role == SUMMARY:
            return source.siblingAtColumn(SUMMARY_COLUMN).data()
        if role == PLANNED:
            return source.data(DOT_ROLE) == "control"
        if role == ROW_ID:
            return self.row_id(index)
        if role == PROBLEM:
            return _PROBLEM_ROLES.get(Mark(source.data(MARK_ROLE)), "") if kind.is_video else ""
        path = model.path(source)
        item = model.library.item(path) if path is not None else None
        episode = item.identity if item is not None and isinstance(item.identity, Episode) else None
        if role == NUMBER:
            return f"{episode.episode:02d}" if episode is not None else ""
        if episode is not None:
            return episode.episode_title or tr("library.episode_untitled", number=episode.episode)
        if kind is Kind.SHOW:
            first = model.library.item(model.video_paths(source)[0])
            year = first.identity.year if first is not None and isinstance(first.identity, Episode) else None
            return tr("library.movie", title=source.data(), year=year) if year else source.data()
        return source.data()

    def index_of(self, row_id: str) -> QModelIndex:
        """The row with `row_id`, or an invalid index when the filter hides it or it is gone."""
        return next((index for index in self._indexes(QModelIndex()) if self.row_id(index) == row_id), QModelIndex())

    def _indexes(self, parent: QModelIndex) -> Iterator[QModelIndex]:
        for row in range(self.rowCount(parent)):
            index = self.index(row, 0, parent)
            yield index
            yield from self._indexes(index)
