"""The empty state: the sheet as a drop target, with the ways to add a library and the state of the programs."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from showrunner.tools.dependencies.detect import DependencyStatus, State
from showrunner.tools.dependencies.specs import SPEC_BY_ID
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.theme.tokens import SIZES

_EXAMPLES = ("show", "episodes", "movies", "subtitles")
# The programs that read tracks, in the order the line names them.
_READERS = ("mkvtoolnix", "ffmpeg")


def _repolish(widget: QWidget) -> None:
    """A changed dynamic property takes effect only once the style is applied again."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class EmptyState(QFrame):
    choose_folder = Signal()
    choose_files = Signal()
    open_dependencies = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "page")
        self.setProperty("drop", "idle")
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        block = QWidget()
        block.setMaximumWidth(SIZES["empty_width"])
        block.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(block, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES["space_lg"])
        self.title = QLabel(tr("empty.title"))
        self.title.setProperty("text_size", "2xl")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        lead = QLabel(tr("empty.lead"))
        lead.setWordWrap(True)
        layout.addWidget(lead)

        buttons = QHBoxLayout()
        buttons.setSpacing(SIZES["space_md"])
        self.folder_button = folder = QPushButton(tr("empty.choose_folder"))
        folder.setProperty("primary", True)
        folder.clicked.connect(self.choose_folder)
        files = QPushButton(tr("empty.choose_files"))
        files.clicked.connect(self.choose_files)
        buttons.addWidget(folder)
        buttons.addWidget(files)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addSpacing(SIZES["space_lg"])

        examples = QGridLayout()
        examples.setHorizontalSpacing(SIZES["space_xl"])
        examples.setVerticalSpacing(SIZES["space_md"])
        for row, key in enumerate(_EXAMPLES):
            label = QLabel(tr(f"empty.example.{key}.label"))
            label.setProperty("role", "muted")
            value = QLabel(tr(f"empty.example.{key}.value"))
            hint = QLabel(tr(f"empty.example.{key}.hint"))
            hint.setProperty("role", "muted")
            line = QHBoxLayout()
            line.setSpacing(0)
            line.addWidget(value)
            line.addWidget(hint)
            line.addStretch()
            examples.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            examples.addLayout(line, row, 1)
        examples.setColumnStretch(1, 1)
        layout.addLayout(examples)
        layout.addSpacing(SIZES["space_lg"])

        self._programs_slot = QVBoxLayout()
        layout.addLayout(self._programs_slot)
        self._programs: QWidget | None = None

    def set_dragging(self, name: str | None) -> None:
        """Show the drop state while something is dragged over the window; `name` is what is being dragged."""
        over = name is not None
        self.title.setText(tr("empty.title_over", name=name) if over else tr("empty.title"))
        self.setProperty("drop", "over" if over else "idle")
        _repolish(self)

    def set_statuses(self, statuses: dict[str, DependencyStatus]) -> None:
        """Say which programs read the tracks, and what is lost for each one that is missing."""
        if self._programs is not None:
            self._programs.hide()
            self._programs.deleteLater()
        found = [
            f"{tr(SPEC_BY_ID[i].name_key)} {s.version}".strip()
            for i in _READERS
            if (s := statuses.get(i)) is not None and s.state is State.FOUND
        ]
        lines: list[tuple[str, str]] = []
        if found:
            lines.append((tr("empty.reads_with", programs=tr("empty.and").join(found)), "muted"))
        for program in _READERS:
            status = statuses.get(program)
            if status is not None and status.state is not State.FOUND:
                spec = SPEC_BY_ID[program]
                features = tr("common.list_separator").join(tr(f"feature.{f.value}") for f in spec.features)
                lines.append((tr("empty.missing", name=tr(spec.name_key), features=features), "notice"))
        box = QWidget()
        rows = QVBoxLayout(box)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(SIZES["space_xs"])
        link = QPushButton(tr("empty.dependencies"))
        link.setFlat(True)
        link.clicked.connect(self.open_dependencies)
        for number, (text, role) in enumerate(lines):
            label = QLabel(text)
            label.setProperty("role", role)
            row = QHBoxLayout()
            row.setSpacing(SIZES["space_sm"])
            row.addWidget(label)
            if found and number == 0:
                row.addWidget(link)  # beside the line about the programs that were found
            else:
                label.setWordWrap(True)
            row.addStretch()
            rows.addLayout(row)
        if not found:
            row = QHBoxLayout()
            row.addWidget(link)
            row.addStretch()
            rows.addLayout(row)
        self._programs_slot.addWidget(box)
        self._programs = box
