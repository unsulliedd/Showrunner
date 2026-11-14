"""Chapters and attachments of one file as small tables."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QHeaderView, QWidget

from showrunner.core.media import Attachment, Chapter
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.sheet.format import duration_text, size_text
from showrunner.ui.sheet.widgets import FitTreeView

_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _cell(text: str, align: Qt.AlignmentFlag = _LEFT) -> QStandardItem:
    cell = QStandardItem(text)
    cell.setEditable(False)
    cell.setTextAlignment(align)
    return cell


def _view(headers: list[str], rows: list[list[QStandardItem]], parent: QWidget | None) -> FitTreeView:
    model = QStandardItemModel(0, len(headers))
    model.setHorizontalHeaderLabels(headers)
    for row in rows:
        model.appendRow(row)
    view = FitTreeView("sheet_list", parent)
    view.setModel(model)
    header = view.header()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    view.fit()
    return view


def chapters_view(chapters: tuple[Chapter, ...], parent: QWidget | None = None) -> FitTreeView:
    rows = [
        [
            _cell(duration_text(chapter.start), _RIGHT),
            _cell(chapter.name_for(None) or tr("sheet.chapter_default", number=number)),
        ]
        for number, chapter in enumerate(chapters, 1)
    ]
    return _view([tr("sheet.chapters.start"), tr("sheet.chapters.name")], rows, parent)


def attachments_view(attachments: tuple[Attachment, ...], parent: QWidget | None = None) -> FitTreeView:
    rows = [[_cell(a.file_name), _cell(size_text(a.size), _RIGHT)] for a in attachments]
    return _view([tr("sheet.attachments.file"), tr("sheet.attachments.size")], rows, parent)
