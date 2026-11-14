"""One field for every typed rule: a single line that underlines the part at fault and says under it what is wrong,
with a button that applies the fix when there is one."""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFocusEvent, QKeyEvent, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from showrunner.ui.settings.page import clear_layout, label, link_button, repolish
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.qt_theme import build_mono_font
from showrunner.ui.theme.tokens import SIZES

# Long enough to skip the keys of a word being typed, short enough to feel live.
EDIT_DELAY_MS = 150


@dataclass(frozen=True, slots=True)
class FieldProblem:
    """`text[start:end]` is at fault. `fix` is the button's label and the text that replaces that range."""

    start: int
    end: int
    message: str
    fix: tuple[str, str] | None = None


def suggest(word: str, choices: Sequence[str]) -> str | None:
    """The closest choice to a mistyped word; one with the same letters wins, since swapped letters are the
    commonest typo."""
    matches = difflib.get_close_matches(word, choices, n=5, cutoff=0.6)
    same = [m for m in matches if sorted(m) == sorted(word)]
    return (same or matches or [None])[0]


def entry_spans(text: str) -> list[tuple[int, int]]:
    """Start and end of each entry of a list field, without the spaces around it; empty entries are skipped,
    as `split_entries` skips them, so the positions match the entries the options hold."""
    spans, start = [], 0
    for part in text.split(","):
        stripped = part.strip()
        offset = start + (len(part) - len(part.lstrip()))
        if stripped:
            spans.append((offset, offset + len(stripped)))
        start += len(part) + 1
    return spans


def split_entries(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


class _Highlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, theme: ThemeManager) -> None:
        super().__init__(document)
        self._theme = theme
        self.ranges: list[tuple[int, int]] = []

    def highlightBlock(self, text: str) -> None:  # noqa: N802  # Qt's name
        form = QTextCharFormat()
        form.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        form.setUnderlineColor(QColor(self._theme.roles["danger"]))
        for start, end in self.ranges:
            self.setFormat(start, max(end - start, 1), form)


class ProblemField(QPlainTextEdit):
    """A single line of code-like text. `edited` fires once typing pauses; `focused` when it takes the focus, so
    the token picker knows where to insert."""

    edited = Signal(str)
    focused = Signal()

    def __init__(self, theme: ThemeManager, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "problem_field")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.setFixedHeight(SIZES["height_md"])
        self.setFont(build_mono_font())
        self.setPlaceholderText(placeholder)
        self.document().setDocumentMargin(SIZES["space_xs"] * 2)
        self._highlighter = _Highlighter(self.document(), theme)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(EDIT_DELAY_MS)
        self._timer.timeout.connect(lambda: self.edited.emit(self.text()))
        self._quiet = False
        self.textChanged.connect(self._on_changed)

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        """Show a value from the options without reporting it as an edit."""
        if text == self.text():
            return
        self._quiet = True
        self.setPlainText(text)
        self._quiet = False

    def set_ranges(self, ranges: list[tuple[int, int]]) -> None:
        self._highlighter.ranges = ranges
        self._highlighter.rehighlight()
        self.setProperty("problem", bool(ranges))
        repolish(self)

    def replace_range(self, start: int, end: int, text: str) -> None:
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.flush()

    def insert(self, text: str) -> None:
        self.textCursor().insertText(text)
        self.setFocus()
        self.flush()

    def flush(self) -> None:
        """Report a pending edit now."""
        self._timer.stop()
        self.edited.emit(self.text())

    def _on_changed(self) -> None:
        if not self._quiet:
            self._timer.start()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802  # Qt's name
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.flush()
            event.ignore()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802  # Qt's name
        super().focusInEvent(event)
        self.focused.emit()

    def insertFromMimeData(self, source) -> None:  # noqa: N802  # Qt's name
        # A pasted line break would make a second line the options cannot hold.
        self.insertPlainText(source.text().replace("\r", " ").replace("\n", " "))


class ProblemEditor(QWidget):
    """The field with one line per problem under it."""

    def __init__(self, theme: ThemeManager, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SIZES["space_xs"])
        self.field = ProblemField(theme, placeholder)
        layout.addWidget(self.field)
        self.messages = QVBoxLayout()
        self.messages.setSpacing(0)
        layout.addLayout(self.messages)
        self.shown: list[str] = []

    def set_problems(self, problems: Sequence[FieldProblem]) -> None:
        self.field.set_ranges([(p.start, p.end) for p in problems])
        clear_layout(self.messages)
        self.shown = [p.message for p in problems]
        for problem in problems:
            row = QHBoxLayout()
            row.setSpacing(SIZES["space_sm"])
            text = label(problem.message, "danger", wrap=True, size="sm")
            row.addWidget(text, 1)
            if problem.fix is not None:
                caption, replacement = problem.fix
                button = link_button(
                    caption, lambda p=problem, r=replacement: self.field.replace_range(p.start, p.end, r)
                )
                row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
            holder = QFrame()
            holder.setLayout(row)
            self.messages.addWidget(holder)
