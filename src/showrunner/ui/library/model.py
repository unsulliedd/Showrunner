"""The library tree's model: shows, seasons and episodes, then movies, built from a `Library`."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel

from showrunner.app.library.library import Library, LibraryLoad, Mark
from showrunner.core.media import Episode, MediaItem, SubtitleFile
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.sheet.format import episode_name, movie_name

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
PATH_ROLE = Qt.ItemDataRole.UserRole + 2
MARK_ROLE = Qt.ItemDataRole.UserRole + 3

NAME_COLUMN, SUMMARY_COLUMN, MARK_COLUMN = range(3)


class Kind(StrEnum):
    SHOW = "show"
    SEASON = "season"
    EPISODE = "episode"
    MOVIES = "movies"
    MOVIE = "movie"

    @property
    def is_video(self) -> bool:
        return self in (Kind.EPISODE, Kind.MOVIE)


class LibraryModel(QStandardItemModel):
    """Three columns: name, summary and mark. A show or season counts its videos and carries the worst mark of
    its rows; an episode or movie lists the languages of its subtitle files."""

    # After any change of the library, whether a rebuild or one pairing.
    library_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(0, 3, parent)
        self._library = Library()
        self._videos: dict[Path, QStandardItem] = {}
        self._order: list[Path] = []  # the videos in tree order

    @property
    def library(self) -> Library:
        return self._library

    # Reading the tree

    def kind(self, index: QModelIndex) -> Kind:
        return Kind(index.siblingAtColumn(NAME_COLUMN).data(KIND_ROLE))

    def path(self, index: QModelIndex) -> Path | None:
        return index.siblingAtColumn(NAME_COLUMN).data(PATH_ROLE)

    def mark(self, index: QModelIndex) -> Mark:
        return Mark(index.siblingAtColumn(NAME_COLUMN).data(MARK_ROLE))

    def index_for_path(self, path: Path) -> QModelIndex:
        item = self._videos.get(path)
        return self.indexFromItem(item) if item is not None else QModelIndex()

    def video_paths(self, index: QModelIndex) -> list[Path]:
        """The videos at or below a row, in tree order."""
        if self.kind(index).is_video:
            return [self.path(index)]
        return [p for row in range(self.rowCount(index)) for p in self.video_paths(self.index(row, 0, index))]

    def first_marked(self) -> QModelIndex:
        """The first video in tree order that needs a look, or an invalid index."""
        return next(
            (self.index_for_path(p) for p in self._order if self._library.mark(p) is not Mark.NONE), QModelIndex()
        )

    # Changing the library

    def set_library(self, library: Library) -> None:
        self._library = library
        self.removeRows(0, self.rowCount())
        self._videos.clear()
        self._order.clear()
        shows: dict[str, tuple[str, dict[int, list[MediaItem]]]] = {}
        movies: list[MediaItem] = []
        for item in library.items:
            identity = item.identity
            if isinstance(identity, Episode):
                seasons = shows.setdefault(identity.show.casefold(), (identity.show, {}))[1]
                seasons.setdefault(identity.season, []).append(item)
            else:
                movies.append(item)
        root = self.invisibleRootItem()
        for _key, (name, seasons) in sorted(shows.items()):
            show = self._add(root, Kind.SHOW, name, str(sum(len(e) for e in seasons.values())))
            for number, episodes in sorted(seasons.items()):
                season = self._add(show, Kind.SEASON, tr("library.season", number=number), str(len(episodes)))
                for item in sorted(episodes, key=lambda i: (i.identity.episode, str(i.file.path))):
                    self._add_video(season, item, episode_name(item.identity))
        if movies:
            group = self._add(root, Kind.MOVIES, tr("library.movies"), str(len(movies)))
            for item in sorted(movies, key=lambda i: (i.identity.title.casefold(), i.identity.year or 0)):
                self._add_video(group, item, movie_name(item.identity))
        for path in self._order:
            if library.mark(path) is not Mark.NONE:
                self._bubble_up(self._videos[path])
        self.library_changed.emit()

    def add(self, load: LibraryLoad) -> None:
        self.set_library(self._library.merge(load))

    def pair(self, subtitle: SubtitleFile, video: Path) -> None:
        self._replace(self._library.pair(subtitle, video))

    def unpair(self, subtitle: SubtitleFile) -> None:
        self._replace(self._library.unpair(subtitle))

    def pair_instead(self, video: Path, subtitle: SubtitleFile) -> None:
        self._replace(self._library.pair_instead(video, subtitle))

    def _replace(self, library: Library) -> None:
        """Take a library with the same videos in the same order and update only the rows that differ."""
        old = self._library
        changed = {a.file.path for a, b in zip(old.items, library.items, strict=True) if a != b}
        changed |= {a.video for a in old.alternatives} ^ {a.video for a in library.alternatives}
        self._library = library
        for path in changed:
            self._refresh_video(path)
        self.library_changed.emit()

    # Rows

    @staticmethod
    def _add(parent: QStandardItem, kind: Kind, text: str, summary: str, path: Path | None = None) -> QStandardItem:
        cells = [QStandardItem(text), QStandardItem(summary), QStandardItem()]
        for cell in cells:
            cell.setEditable(False)
            cell.setData(int(Mark.NONE), MARK_ROLE)
        cells[NAME_COLUMN].setData(kind.value, KIND_ROLE)
        cells[NAME_COLUMN].setData(path, PATH_ROLE)
        cells[SUMMARY_COLUMN].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        parent.appendRow(cells)
        return cells[NAME_COLUMN]

    def _add_video(self, parent: QStandardItem, item: MediaItem, text: str) -> None:
        path = item.file.path
        kind = Kind.EPISODE if isinstance(item.identity, Episode) else Kind.MOVIE
        cell = self._add(parent, kind, text, "", path)
        self._videos[path] = cell
        self._order.append(path)
        self._refresh_video(path)

    def _languages(self, item: MediaItem) -> str:
        codes = dict.fromkeys(
            s.language.alpha3 if s.language else tr("library.language_unknown") for s in item.subtitles
        )
        return tr("common.list_separator").join(codes) if codes else tr("common.none")

    def _set_mark(self, cell: QStandardItem, mark: Mark) -> None:
        """Set the mark on every cell of the row of `cell`."""
        parent = cell.parent() or self.invisibleRootItem()
        for column in range(self.columnCount()):
            parent.child(cell.row(), column).setData(int(mark), MARK_ROLE)

    def _refresh_video(self, path: Path) -> None:
        cell = self._videos[path]
        item = self._library.item(path)
        assert item is not None
        mark = self._library.mark(path)
        (cell.parent() or self.invisibleRootItem()).child(cell.row(), SUMMARY_COLUMN).setText(self._languages(item))
        self._set_mark(cell, mark)
        if mark is Mark.FAILED:
            cell.setToolTip(tr("library.tip.failed", reason=self._library.failure(path)))
        else:
            cell.setToolTip(tr("library.tip.unsure") if mark is Mark.UNSURE else "")
        self._bubble_up(cell)

    def _bubble_up(self, cell: QStandardItem) -> None:
        """Give each ancestor of `cell` the worst mark among its rows."""
        parent = cell.parent()
        while parent is not None:
            marks = (Mark(parent.child(row, NAME_COLUMN).data(MARK_ROLE)) for row in range(parent.rowCount()))
            self._set_mark(parent, max(marks, default=Mark.NONE))
            parent = parent.parent()
