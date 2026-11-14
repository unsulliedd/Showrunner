"""The tracks of one file as a tree grouped by kind, with the track flags drawn as chips."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QHeaderView, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from showrunner.core.media import MediaFile
from showrunner.core.track import Track, TrackFlags, TrackKind
from showrunner.stages.tracks import PlannedTrack, TrackPlan
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


@dataclass(frozen=True, slots=True)
class TablePlan:
    """What a preview plans for the tracks of one file: the track plan, the names Metadata writes by track ID,
    and the colors of the theme to draw them with."""

    tracks: TrackPlan | None
    names: dict[int, str]
    roles: dict[str, str]


class TrackModel(QStandardItemModel):
    """One group row per kind that has tracks, with the tracks below it. With a plan, a dropped track is struck
    out and muted, an added subtitle file is listed with `+`, and a new name is drawn in the `control` color with
    the old one as its tooltip."""

    def __init__(self, media: MediaFile, plan: TablePlan | None = None, parent: QWidget | None = None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels([tr(f"sheet.tracks.{c}") for c in ("id", "language", "codec", "name", "flags")])
        self._plan = plan
        tracks = plan.tracks if plan else None
        self._dropped = {d.track.id for d in tracks.dropped if d.external is None} if tracks else set()
        self._kept = {k.track.id: k for k in tracks.kept if k.external is None} if tracks else {}
        added = [k for k in tracks.kept if k.external is not None] if tracks else []
        for kind in _KINDS:
            rows = [(t, None) for t in media.tracks if t.kind is kind]
            rows += [(k.track, k) for k in added if k.track.kind is kind]
            if rows:
                self._add_group(kind, rows)

    def _add_group(self, kind: TrackKind, rows: list[tuple[Track, PlannedTrack | None]]) -> None:
        group = _cell(tr(f"sheet.kind.{kind.value}", count=len(rows)))
        font = QFont(group.font())
        font.setWeight(QFont.Weight.DemiBold)
        group.setFont(font)
        self.appendRow([group, *(_cell("") for _ in range(4))])
        plan = self._plan
        for track, added in rows:
            planned = added or self._kept.get(track.id)
            new_name = plan.names.get(track.id) if plan and added is None else None
            dropped = track.id in self._dropped
            changed = bool(planned and planned.flag_changes) or new_name is not None
            mark = "+" if added else "\N{MINUS SIGN}" if dropped else "\N{BULLET}" if changed else ""
            number = f"{mark} {track.id}" if mark and not added else (mark or str(track.id))
            name = added.external.path.name if added and added.external else (new_name or track.name)
            cells = [
                _cell(number, Qt.AlignmentFlag.AlignRight),
                _cell(language_code(track.language)),
                _cell(track_summary(track)),
                _cell(name or tr("common.none")),
                _cell(""),
            ]
            flags = planned.flags if planned is not None else track.flags
            cells[FLAGS_COLUMN].setData([] if dropped else flag_names(flags), FLAGS_ROLE)
            if plan is not None and dropped:
                for cell in cells:
                    struck = QFont(cell.font())
                    struck.setStrikeOut(True)
                    cell.setFont(struck)
                    cell.setForeground(QColor(plan.roles["muted"]))
                cells[FLAGS_COLUMN].setText(tr("sheet.dropped"))
            elif plan is not None and new_name is not None:
                cells[NAME_COLUMN].setForeground(QColor(plan.roles["control"]))
                cells[NAME_COLUMN].setToolTip(tr("sheet.old_name", name=track.name or tr("common.none")))
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
            super().paint(painter, option, index)
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

    def show_media(self, media: MediaFile, plan: TablePlan | None = None) -> None:
        self.setModel(TrackModel(media, plan, self))
        self.expandAll()
        for row in range(self.model().rowCount()):
            self.setFirstColumnSpanned(row, QModelIndex(), True)
        header = self.header()
        header.setStretchLastSection(False)
        for column in range(5):
            mode = QHeaderView.ResizeMode.Stretch if column == NAME_COLUMN else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)
        self.fit()
