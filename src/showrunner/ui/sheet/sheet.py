"""The sheet: the title row, then either one video in detail or the group of videos that was selected."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.library.library import Library, Mark
from showrunner.core.media import MediaFile, SubtitleFile
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.marks import MarkDot
from showrunner.ui.sheet.details import DetailsPanel, file_row
from showrunner.ui.sheet.format import SEPARATOR, count_parts, duration_text, item_title, size_text
from showrunner.ui.sheet.lists import attachments_view, chapters_view
from showrunner.ui.sheet.tracks import TablePlan, TracksView
from showrunner.ui.sheet.widgets import ElidedLabel, heading, replace_content
from showrunner.ui.shell.splitter import SavedSplitter
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    return label


class Sheet(QFrame):
    """The page on the right of the window.

    It stays in one of three states: nothing selected, a video, or a group (a show, a season or the movies).
    """

    unpair_requested = Signal(object)  # the SubtitleFile
    pair_instead_requested = Signal(object, object)  # the video's path, the SubtitleFile
    pair_here_requested = Signal(object, object)  # the SubtitleFile, the video's path

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setProperty("role", "page")
        layout = QVBoxLayout(self)
        margin = SIZES["space_xl"]
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(SIZES["space_lg"])

        self.title = ElidedLabel()
        self.title.setProperty("text_size", "2xl")
        self.path_label = ElidedLabel()
        self.path_label.setProperty("role", "muted")
        self.path_label.setProperty("text_size", "sm")
        self.meta_label = _muted()
        self.meta_label.setProperty("text_size", "sm")
        self.dot = MarkDot(theme)
        self.state = QLabel()

        title_row = QHBoxLayout()
        title_row.setSpacing(SIZES["space_md"])
        left = QVBoxLayout()
        left.setSpacing(SIZES["space_xs"])
        left.addWidget(self.title)
        line = QHBoxLayout()
        line.setSpacing(SIZES["space_sm"])
        line.addWidget(self.path_label, 1)
        line.addWidget(self.meta_label)
        left.addLayout(line)
        title_row.addLayout(left, 1)
        state_row = QHBoxLayout()
        state_row.setSpacing(SIZES["space_sm"])
        state_row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        state_row.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addLayout(state_row)
        self.title_row = QWidget()
        self.title_row.setLayout(title_row)
        title_row.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title_row)

        self.sections = QScrollArea()
        self.sections.setWidgetResizable(True)
        self.sections.setFrameShape(QFrame.Shape.NoFrame)
        self.sections.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.details = DetailsPanel()
        self.details.unpair_requested.connect(self.unpair_requested)
        self.details.pair_instead_requested.connect(self.pair_instead_requested)
        self.details.pair_here_requested.connect(self.pair_here_requested)
        self.splitter = SavedSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(SIZES["space_xs"] + 1)
        self.splitter.addWidget(self.sections)
        self.splitter.addWidget(self.details)
        self.splitter.setCollapsible(0, False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        layout.addWidget(self.splitter, 1)

        self.group_area = QScrollArea()
        self.group_area.setWidgetResizable(True)
        self.group_area.setFrameShape(QFrame.Shape.NoFrame)
        self.group_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.group_area, 1)
        self.show_placeholder()

    # States

    def show_placeholder(self) -> None:
        self._header(visible=False)
        self.splitter.hide()
        hint = _muted(tr("sheet.placeholder"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_group(hint)

    def show_item(
        self,
        library: Library,
        path: Path,
        *,
        plan: QWidget | None = None,
        table_plan: TablePlan | None = None,
        state: tuple[str, str | None] | None = None,
    ) -> None:
        """`plan` is the planned-changes section, `table_plan` what it does to the tracks, `state` the title
        row's words and dot role after a preview; a mark of the library itself wins over that state."""
        item = library.item(path)
        if item is None:
            self.show_placeholder()
            return
        self._header(visible=True)
        self.group_area.hide()
        self.splitter.show()
        self.title.set_full_text(item_title(item))
        self.path_label.set_full_text(str(library.relative_path(path)))
        meta = [size_text(item.file.size)] if item.file.size else []
        if item.file.duration:
            meta.append(duration_text(item.file.duration))
        self.meta_label.setText(SEPARATOR.join(meta))
        mark = library.mark(path)
        self.dot.set_mark(mark)
        self._set_state(mark, library.failure(path))
        if state is not None and mark is Mark.NONE:
            words, role = state
            self.dot.set_role(role)
            self.state.setText(words)
            self.state.setProperty("role", "notice" if role == "accent_ink" else "")
            self.state.style().unpolish(self.state)
            self.state.style().polish(self.state)
        replace_content(self.sections, self._sections(item.file, library.failure(path), plan, table_plan))
        self.details.show_item(library, path)

    def show_group(self, name: str, library: Library, paths: list[Path]) -> None:
        """A show, a season or the movies: the counts and the unpaired subtitle files beside its videos."""
        self._header(visible=True)
        self.splitter.hide()
        self.title.set_full_text(name)
        self.path_label.set_full_text(
            SEPARATOR.join(text for text, _ in count_parts(library.counts(paths), breakdown=False))
        )
        self.meta_label.setText("")
        self.dot.set_mark(Mark.NONE)
        self._set_state(Mark.NONE, None)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES["space_md"])
        unpaired = library.unpaired_near(paths)
        layout.addWidget(heading(tr("details.unpaired"), len(unpaired)))
        if not unpaired:
            layout.addWidget(_muted(tr("sheet.group.no_unpaired")))
        for subtitle in unpaired:
            layout.addWidget(file_row(subtitle, self._pair_menu_button(paths, subtitle)))
        layout.addStretch()
        self._set_group(content)

    # Parts

    def _header(self, *, visible: bool) -> None:
        self.title_row.setVisible(visible)

    def _set_group(self, content: QWidget) -> None:
        replace_content(self.group_area, content)
        self.group_area.show()

    def _set_state(self, mark: Mark, reason: str | None) -> None:
        text = {Mark.UNSURE: tr("sheet.state.unsure"), Mark.FAILED: tr("sheet.state.failed")}.get(mark, "")
        self.state.setText(text)
        self.state.setToolTip(reason or "")
        self.state.setProperty("role", {Mark.UNSURE: "notice", Mark.FAILED: "danger"}.get(mark, ""))
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def _sections(
        self, media: MediaFile, failure: str | None, plan: QWidget | None, table_plan: TablePlan | None
    ) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, SIZES["space_xl"], 0)
        layout.setSpacing(SIZES["space_md"])
        if plan is not None:
            layout.addWidget(plan)
            layout.addSpacing(SIZES["space_lg"])

        layout.addWidget(heading(tr("sheet.tracks"), len(media.tracks)))
        if media.tracks:
            view = TracksView(self._theme)
            view.show_media(media, table_plan)
            layout.addWidget(view)
        elif failure:
            reason = QLabel(tr("sheet.tracks_failed", reason=failure))
            reason.setProperty("role", "danger")
            reason.setWordWrap(True)
            layout.addWidget(reason)
        else:
            layout.addWidget(_muted(tr("sheet.tracks_not_read")))

        layout.addSpacing(SIZES["space_lg"])
        lower = QHBoxLayout()
        lower.setSpacing(SIZES["space_xl"])
        lower.addLayout(self._column(tr("sheet.chapters"), media.chapters, chapters_view), 1)
        lower.addLayout(self._column(tr("sheet.attachments"), media.attachments, attachments_view), 1)
        layout.addLayout(lower)
        layout.addStretch()
        return content

    @staticmethod
    def _column(title: str, rows: tuple, build: Callable[[tuple], QWidget]) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(SIZES["space_md"])
        column.addWidget(heading(title, len(rows)))
        if rows:
            column.addWidget(build(rows))
        else:
            column.addWidget(_muted(tr("sheet.none")))
        column.addStretch()
        return column

    def _pair_menu_button(self, paths: list[Path], subtitle: SubtitleFile) -> QPushButton:
        """ "A button that opens a menu of the videos in the subtitle file's folder."""
        button = QPushButton(tr("sheet.group.pair_to"))
        button.setFlat(True)
        menu = QMenu(button)
        folders = {subtitle.path.parent, subtitle.path.parent.parent}
        for video in (p for p in paths if p.parent in folders):
            action = menu.addAction(video.name)
            action.triggered.connect(lambda _=False, v=video: self.pair_here_requested.emit(subtitle, v))
        button.setMenu(menu)
        return button
