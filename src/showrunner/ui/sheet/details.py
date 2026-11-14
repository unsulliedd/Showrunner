"""The details panel: what the file was recognized as and which subtitle files are paired with it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from showrunner.app.library.library import Library
from showrunner.core.media import Episode, Movie, SubtitleFile
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.sheet.format import SEPARATOR, subtitle_format
from showrunner.ui.sheet.widgets import ElidedLabel, heading, replace_content
from showrunner.ui.theme.tokens import SIZES


def subtitle_detail(subtitle: SubtitleFile) -> str:
    """Language, format and the flags the file name carries, on one line."""
    parts = [subtitle.language.name if subtitle.language else tr("details.language_unknown")]
    parts.append(subtitle_format(subtitle.path))
    if subtitle.forced:
        parts.append(tr("sheet.flag.forced"))
    if subtitle.sdh:
        parts.append(tr("sheet.flag.sdh"))
    return SEPARATOR.join(parts)


def file_row(subtitle: SubtitleFile, action: QWidget) -> QWidget:
    """A subtitle file's name and detail on the left and an action on the right."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SIZES["space_md"])
    text = QVBoxLayout()
    text.setSpacing(0)
    name = ElidedLabel()
    name.set_full_text(subtitle.path.name)
    detail = QLabel(subtitle_detail(subtitle))
    detail.setProperty("role", "muted")
    detail.setProperty("text_size", "sm")
    text.addWidget(name)
    text.addWidget(detail)
    layout.addLayout(text, 1)
    layout.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


def action_button(text: str, on_click: Callable[[], None], *, flat: bool) -> QPushButton:
    button = QPushButton(text)
    button.setFlat(flat)
    button.clicked.connect(lambda _checked=False: on_click())
    return button


class DetailsPanel(QScrollArea):
    """Identity, paired subtitle files and the unpaired ones in the same folder, each with its action."""

    unpair_requested = Signal(object)  # the SubtitleFile
    pair_instead_requested = Signal(object, object)  # the video's path, the SubtitleFile
    pair_here_requested = Signal(object, object)  # the SubtitleFile, the video's path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def sizeHint(self) -> QSize:  # noqa: N802  # Qt's name
        """The width the panel gets before the user has dragged the splitter."""
        return QSize(SIZES["details_width"], super().sizeHint().height())

    def show_item(self, library: Library, path: Path) -> None:
        item = library.item(path)
        if item is None:
            return
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SIZES["space_xl"], 0, 0, 0)
        layout.setSpacing(SIZES["space_md"])

        layout.addWidget(heading(tr("details.identity")))
        layout.addLayout(self._identity(item.identity))

        layout.addSpacing(SIZES["space_md"])
        layout.addWidget(heading(tr("details.subtitles"), len(item.subtitles)))
        if not item.subtitles:
            empty = QLabel(tr("details.no_subtitles"))
            empty.setProperty("role", "muted")
            layout.addWidget(empty)
        for subtitle in item.subtitles:
            unpair = action_button(tr("details.unpair"), lambda s=subtitle: self.unpair_requested.emit(s), flat=True)
            layout.addWidget(file_row(subtitle, unpair))
        alternatives = library.alternatives_of(path)
        if alternatives:
            notice = QLabel(tr_plural("details.unsure", len(alternatives)))
            notice.setProperty("role", "notice")
            notice.setWordWrap(True)
            layout.addWidget(notice)
            for subtitle in alternatives:
                pair = action_button(
                    tr("details.pair_instead"), lambda s=subtitle: self.pair_instead_requested.emit(path, s), flat=False
                )
                layout.addWidget(file_row(subtitle, pair))

        unpaired = library.unpaired_near([path])
        if unpaired:
            layout.addSpacing(SIZES["space_md"])
            layout.addWidget(heading(tr("details.unpaired"), len(unpaired)))
            for subtitle in unpaired:
                here = action_button(
                    tr("details.pair_here"), lambda s=subtitle: self.pair_here_requested.emit(s, path), flat=True
                )
                layout.addWidget(file_row(subtitle, here))
        layout.addStretch()
        replace_content(self, content)

    def clear(self) -> None:
        replace_content(self, QWidget())

    @staticmethod
    def _identity(identity: Movie | Episode) -> QFormLayout:
        form = QFormLayout()
        form.setHorizontalSpacing(SIZES["space_xl"])
        form.setVerticalSpacing(SIZES["space_sm"])
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        if isinstance(identity, Episode):
            rows = [
                ("show", identity.show),
                ("year", identity.year),
                ("season", identity.season),
                ("episode", identity.episode),
                ("title", identity.episode_title),
            ]
        else:
            rows = [("title", identity.title), ("year", identity.year)]
        for key, value in rows:
            label = QLabel(tr(f"details.identity.{key}"))
            label.setProperty("role", "muted")
            text = QLabel(str(value) if value not in (None, "") else tr("common.none"))
            text.setWordWrap(True)
            form.addRow(label, text)
        return form
