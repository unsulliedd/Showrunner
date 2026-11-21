"""The library tree's model: shows with their seasons and episodes, then their extras, then movies, built from a
`Library`."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel

from showrunner.app.library.library import Library, LibraryLoad, Mark
from showrunner.core.media import Episode, Extra, MediaFile, MediaItem, Movie, SubtitleFile
from showrunner.ui.i18n.catalog import tr

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
PATH_ROLE = Qt.ItemDataRole.UserRole + 2
MARK_ROLE = Qt.ItemDataRole.UserRole + 3
# What the row's dot says: the library's own mark, else the mark of the last preview; a parent's is the worst of its
# rows. The values are "failed", "needs_look" and "planned".
DOT_ROLE = Qt.ItemDataRole.UserRole + 4
# Whether the last preview plans a change at or below the row. Kept apart from the dot, which shows only the worst of
# a parent's rows, so a season with one file that needs a look still says it has changes planned.
PLANNED_ROLE = Qt.ItemDataRole.UserRole + 5

# Worst first: could not be read, needs a decision (unsure pairing or a refused plan), changes planned.
DOT_RANK = {"failed": 3, "needs_look": 2, "planned": 1}
_LIBRARY_DOTS = {Mark.FAILED: "failed", Mark.UNSURE: "needs_look"}

NAME_COLUMN, SUMMARY_COLUMN, MARK_COLUMN = range(3)


def movie_name(movie: Movie) -> str:
    return tr("library.movie", title=movie.title, year=movie.year) if movie.year else movie.title


def episode_name(episode: Episode) -> str:
    return tr("library.episode", number=episode.episode, title=episode.episode_title).rstrip()


class Kind(StrEnum):
    SHOW = "show"
    SEASON = "season"
    EPISODE = "episode"
    EXTRAS = "extras"
    EXTRA = "extra"
    MOVIES = "movies"
    MOVIE = "movie"

    @property
    def is_video(self) -> bool:
        return self in (Kind.EPISODE, Kind.EXTRA, Kind.MOVIE)


class LibraryModel(QStandardItemModel):
    """Three columns: name, summary and mark. A show or season counts its videos and carries the worst mark of
    its rows; an episode or movie lists the languages of its subtitle files."""

    # After any change of the library, whether a rebuild or one pairing.
    library_changed = Signal()
    # After the dots changed without the library changing: a preview's marks were set or cleared.
    marks_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(0, 3, parent)
        self._library = Library()
        self._videos: dict[Path, QStandardItem] = {}
        self._order: list[Path] = []  # the videos in tree order
        self._plan: dict[Path, str] = {}  # video -> dot color role from the last preview
        self._excluded: frozenset[Path] = frozenset()  # videos out of every run: they carry no dot and need no look

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

    def dot(self, path: Path) -> str | None:
        if path in self._excluded:
            return None
        return _LIBRARY_DOTS.get(self._library.mark(path)) or self._plan.get(path)

    def needs_look_count(self) -> int:
        """Videos that need a decision: the library's marks plus the refused plans of the last preview."""
        return sum(self.dot(p) in ("failed", "needs_look") for p in self._order)

    def set_plan_marks(self, marks: dict[Path, str]) -> None:
        """Dots from a preview, by video path; an empty dict clears them."""
        self._plan = dict(marks)
        for path in self._order:
            self._refresh_dot(path, bubble=False)
        self._bubble_all(self._videos[path] for path in self._order)
        self.marks_changed.emit()

    def set_excluded(self, paths: Iterable[Path]) -> None:
        """The videos that are excluded: their dots go, and come back when they are included again."""
        paths = frozenset(paths)
        changed = self._excluded ^ paths
        self._excluded = paths
        shown = changed & self._videos.keys()
        for path in shown:
            self._refresh_dot(path, bubble=False)
        self._bubble_all(self._videos[path] for path in shown)
        if changed:
            self.marks_changed.emit()

    # Changing the library

    def set_library(self, library: Library) -> None:
        self._library = library
        self.removeRows(0, self.rowCount())
        self._videos.clear()
        self._order.clear()
        shows: dict[str, tuple[str, dict[int, list[MediaItem]], list[MediaItem]]] = {}
        movies: list[MediaItem] = []
        for item in library.items:
            identity = item.identity
            if isinstance(identity, Episode):
                seasons = shows.setdefault(identity.show.casefold(), (identity.show, {}, []))[1]
                seasons.setdefault(identity.season, []).append(item)
            elif isinstance(identity, Extra):
                shows.setdefault(identity.show.casefold(), (identity.show, {}, []))[2].append(item)
            else:
                movies.append(item)
        root = self.invisibleRootItem()
        for _key, (name, seasons, extras) in sorted(shows.items()):
            count = sum(len(e) for e in seasons.values()) + len(extras)
            show = self._add(root, Kind.SHOW, name, str(count))
            for number, episodes in sorted(seasons.items()):
                season = self._add(show, Kind.SEASON, tr("library.season", number=number), str(len(episodes)))
                for item in sorted(episodes, key=lambda i: (i.identity.episode, str(i.file.path))):
                    self._add_video(season, item, episode_name(item.identity))
            if extras:
                group = self._add(show, Kind.EXTRAS, tr("library.extras"), str(len(extras)))
                for item in sorted(extras, key=lambda i: (i.identity.title.casefold(), str(i.file.path))):
                    self._add_video(group, item, item.identity.title)
        if movies:
            group = self._add(root, Kind.MOVIES, tr("library.movies"), str(len(movies)))
            for item in sorted(movies, key=lambda i: (i.identity.title.casefold(), i.identity.year or 0)):
                self._add_video(group, item, movie_name(item.identity))
        for path in self._order:
            if self.dot(path) is not None:
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

    def replace_files(self, files: dict[Path, MediaFile], gone: Iterable[Path] = ()) -> None:
        """Take the files read again after Apply in place of the ones the library holds; see `Library.with_files`."""
        library = self._library.with_files(files, gone)
        if [i.file.path for i in library.items] == [i.file.path for i in self._library.items]:
            self._replace(library)
        else:
            self.set_library(library)  # a file took a new name, which the rows are keyed by

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
        kind = {Episode: Kind.EPISODE, Extra: Kind.EXTRA}.get(type(item.identity), Kind.MOVIE)
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
        self._refresh_dot(path, bubble=False)
        if mark is Mark.FAILED:
            cell.setToolTip(tr("library.tip.failed", reason=self._library.failure(path)))
        else:
            cell.setToolTip(tr("library.tip.unsure") if mark is Mark.UNSURE else "")
        self._bubble_up(cell)

    def _set_dot(self, cell: QStandardItem, dot: str | None, planned: bool) -> None:
        parent = cell.parent() or self.invisibleRootItem()
        for column in range(self.columnCount()):
            parent.child(cell.row(), column).setData(dot, DOT_ROLE)
            parent.child(cell.row(), column).setData(planned, PLANNED_ROLE)

    def _refresh_dot(self, path: Path, *, bubble: bool = True) -> None:
        cell = self._videos[path]
        self._set_dot(cell, self.dot(path), path not in self._excluded and self._plan.get(path) == "planned")
        if bubble:
            self._bubble_up(cell)

    def _bubble_up(self, cell: QStandardItem) -> None:
        """Give each ancestor of `cell` the worst mark and the worst dot among its rows."""
        parent = cell.parent()
        while parent is not None:
            self._sum_up(parent)
            parent = parent.parent()

    def _bubble_all(self, cells: Iterable[QStandardItem]) -> None:
        """`_bubble_up` for many cells, each ancestor summed up once per level it is found at rather than once per
        cell below it: an ancestor's last sum comes after every row below it was summed for the last time."""
        level = {id(p): p for cell in cells if (p := cell.parent()) is not None}
        while level:
            for parent in level.values():
                self._sum_up(parent)
            level = {id(p): p for parent in level.values() if (p := parent.parent()) is not None}

    def _sum_up(self, parent: QStandardItem) -> None:
        marks = (Mark(parent.child(row, NAME_COLUMN).data(MARK_ROLE)) for row in range(parent.rowCount()))
        self._set_mark(parent, max(marks, default=Mark.NONE))
        rows = [parent.child(row, NAME_COLUMN) for row in range(parent.rowCount())]
        dots = [row.data(DOT_ROLE) for row in rows]
        planned = any(row.data(PLANNED_ROLE) for row in rows)
        self._set_dot(parent, max(dots, key=lambda d: DOT_RANK.get(d, 0), default=None), planned)
