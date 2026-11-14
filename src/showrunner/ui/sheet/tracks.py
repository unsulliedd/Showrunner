"""The tracks of one file as a tree grouped by kind, with the track flags drawn as chips."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QHeaderView, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from showrunner.core.media import MediaFile
from showrunner.core.track import Track, TrackFlags, TrackKind
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.sheet.format import language_code, track_summary
from showrunner.ui.sheet.widgets import FitTreeView
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES

FLAGS_ROLE = Qt.ItemDataRole.UserRole + 1
ID_COLUMN, LANGUAGE_COLUMN, CODEC_COLUMN, NAME_COLUMN, FLAGS_COLUMN = range(5)

_KINDS = (TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.SUBTITLE)
# The attribute of `TrackFlags` and the string key suffix of each flag, in display order.
_FLAGS = (
    ("default", "default"),
    ("forced", "forced"),
    ("hearing_impaired", "sdh"),
    ("visual_impaired", "visual_impaired"),
    ("commentary", "commentary"),
    ("original", "original"),
)


def flag_names(flags: TrackFlags) -> list[str]:
    return [tr(f"sheet.flag.{key}") for attribute, key in _FLAGS if getattr(flags, attribute)]


def _cell(text: str, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft) -> QStandardItem:
    cell = QStandardItem(text)
    cell.setEditable(False)
    cell.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    return cell


class TrackModel(QStandardItemModel):
    """One group row per kind that has tracks, with the tracks below it."""

    def __init__(self, media: MediaFile, parent: QWidget | None = None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels([tr(f"sheet.tracks.{c}") for c in ("id", "language", "codec", "name", "flags")])
        for kind in _KINDS:
            tracks = [t for t in media.tracks if t.kind is kind]
            if tracks:
                self._add_group(kind, tracks)

    def _add_group(self, kind: TrackKind, tracks: list[Track]) -> None:
        group = _cell(tr(f"sheet.kind.{kind.value}", count=len(tracks)))
        font = QFont(group.font())
        font.setWeight(QFont.Weight.DemiBold)
        group.setFont(font)
        self.appendRow([group, *(_cell("") for _ in range(4))])
        for track in tracks:
            cells = [
                _cell(str(track.id), Qt.AlignmentFlag.AlignRight),
                _cell(language_code(track.language)),
                _cell(track_summary(track)),
                _cell(track.name or tr("common.none")),
                _cell(""),
            ]
            cells[FLAGS_COLUMN].setData(flag_names(track.flags), FLAGS_ROLE)
            group.appendRow(cells)


class FlagsDelegate(QStyledItemDelegate):
    """Draws a track's flags as small chips side by side."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

    @staticmethod
    def _chip_font(option: QStyleOptionViewItem) -> QFont:
        font = QFont(option.font)
        font.setPixelSize(SIZES["text_xs"])
        return font

    def _chips(self, option: QStyleOptionViewItem, names: list[str]) -> list[tuple[str, float]]:
        metrics = QFontMetrics(self._chip_font(option))
        return [(name, metrics.horizontalAdvance(name) + 2 * SIZES["space_md"]) for name in names]

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        names = index.data(FLAGS_ROLE) or []
        if not names:
            return
        roles = self._theme.roles
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._chip_font(option))
        height = painter.fontMetrics().height() + 2 * SIZES["space_xs"]
        x = option.rect.left() + SIZES["space_sm"]
        top = option.rect.center().y() - height / 2 + 0.5
        for name, width in self._chips(option, names):
            rect = QRectF(x, top, width, height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(roles["chrome_2"]))
            painter.drawRoundedRect(rect, SIZES["radius_sm"], SIZES["radius_sm"])
            painter.setPen(QPen(QColor(roles["ink"])))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), name)
            x += width + SIZES["space_sm"]
        painter.restore()

    def sizeHint(  # noqa: N802  # Qt's name
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        chips = self._chips(option, index.data(FLAGS_ROLE) or [])
        return QSize(int(sum(width + SIZES["space_sm"] for _, width in chips) + SIZES["space_sm"]), SIZES["row_md"])


class TracksView(FitTreeView):
    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__("tracks", parent)
        self._flags = FlagsDelegate(theme, self)
        self.setItemDelegateForColumn(FLAGS_COLUMN, self._flags)

    def show_media(self, media: MediaFile) -> None:
        self.setModel(TrackModel(media, self))
        self.expandAll()
        for row in range(self.model().rowCount()):
            self.setFirstColumnSpanned(row, QModelIndex(), True)
        header = self.header()
        header.setStretchLastSection(False)
        for column in range(5):
            mode = QHeaderView.ResizeMode.Stretch if column == NAME_COLUMN else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)
        self.fit()
