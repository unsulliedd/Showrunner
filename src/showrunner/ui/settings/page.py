"""What every Settings page shares: the title row, a body that scrolls, and the footer of the profile pages."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.profiles.errors import ProfileError
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.theme.tokens import SIZES


def repolish(widget: QWidget) -> None:
    """A changed dynamic property takes effect only once the style is applied again."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text: str = "", role: str = "", *, wrap: bool = False, size: str = "") -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if size:
        widget.setProperty("text_size", size)
    widget.setWordWrap(wrap)
    return widget


def heading(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setProperty("heading", True)
    return widget


def link_button(text: str, slot: Callable[[], object] | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setFlat(True)
    button.setProperty("flat", True)
    if slot is not None:
        button.clicked.connect(lambda _=False: slot())
    return button


def clear_layout(layout: QLayout) -> None:
    """Remove and delete every widget and inner layout; the widgets go later, since a slot of one may be running."""
    while layout.count():
        item = layout.takeAt(0)
        if (widget := item.widget()) is not None:
            widget.hide()
            widget.deleteLater()
        elif (inner := item.layout()) is not None:
            clear_layout(inner)


class SettingsPage(QWidget):
    """Title and lead at the top, `body` below them in a scroll area, and an optional footer under that."""

    def __init__(self, title: str, lead: str, *, scroll: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QWidget()
        self.title_row = QHBoxLayout(top)
        margin = SIZES["space_xl"]
        self.title_row.setContentsMargins(margin, margin, margin, SIZES["space_lg"])
        self.title_row.setSpacing(SIZES["space_lg"])
        text = QVBoxLayout()
        text.setSpacing(SIZES["space_xs"])
        self.title = label(title, size="2xl")
        text.addWidget(self.title)
        self.lead = label(lead, "muted", wrap=True, size="sm")
        text.addWidget(self.lead)
        self.title_row.addLayout(text, 1)
        outer.addWidget(top)

        content = QWidget()
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(margin, 0, margin, margin)
        self.body.setSpacing(SIZES["space_lg"])
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            area.setWidget(content)
            outer.addWidget(area, 1)
        else:
            outer.addWidget(content, 1)
        self._outer = outer

    def add_footer(self, footer: QWidget) -> None:
        self._outer.addWidget(footer)


class ProfileFooter(QWidget):
    """The status of the working copy with Revert, Save as… and Save. `problems` gives the page's own problem line,
    shown in place of the status while there is one."""

    def __init__(
        self, session: ProfileSession, problems: Callable[[], str] = lambda: "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._problems = problems
        self.setProperty("role", "footer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(self)
        margin = SIZES["space_xl"]
        layout.setContentsMargins(margin, SIZES["space_md"], margin, SIZES["space_md"])
        layout.setSpacing(SIZES["space_md"])
        self.status = label(size="sm", wrap=True)
        layout.addWidget(self.status, 1)
        self.revert = QPushButton(tr("settings.revert"))
        self.revert.clicked.connect(session.revert)
        self.save_as = QPushButton(tr("settings.save_as"))
        self.save_as.clicked.connect(self.ask_save_as)
        self.save = QPushButton(tr("settings.save"))
        self.save.clicked.connect(self._save)
        for button in (self.revert, self.save_as, self.save):
            layout.addWidget(button)
        session.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        session = self._session
        changed = session.is_changed
        problems = self._problems()
        if problems:
            text, role = problems, "danger"
        elif session.read_only and changed:
            text, role = tr("settings.default_read_only"), "notice"
        elif changed:
            text, role = tr("settings.footer.unsaved", name=session.name), "muted"
        else:
            text, role = tr("settings.footer.saved", name=session.name), "muted"
        self.status.setText(text)
        self.status.setProperty("role", role)
        repolish(self.status)
        self.revert.setEnabled(changed)
        self.save.setEnabled(changed and not session.read_only)
        self.save.setProperty("primary", not session.read_only)
        self.save_as.setProperty("primary", session.read_only)
        repolish(self.save)
        repolish(self.save_as)

    def _save(self) -> None:
        try:
            self._session.save()
        except (ProfileError, OSError) as error:
            QMessageBox.warning(self, tr("settings.save"), tr("settings.save_failed", error=error))

    def ask_name(self) -> str:
        """The name for Save as…; empty when the user cancels."""
        name, ok = QInputDialog.getText(self, tr("settings.save_as_title"), tr("settings.save_as_label"))
        return name.strip() if ok else ""

    def ask_save_as(self) -> None:
        if not (name := self.ask_name()):
            return
        try:
            self._session.save_as(name)
        except (ProfileError, OSError) as error:
            QMessageBox.warning(
                self, tr("settings.save_as_title"), tr("settings.save_as_failed", name=name, error=error)
            )


class Segmented(QWidget):
    """Checkable buttons side by side, one of them on: `chosen` carries the value of the one clicked."""

    chosen = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.buttons: dict[str, QPushButton] = {}
        for number, (value, text) in enumerate(options):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            place = "first" if number == 0 else "last" if number == len(options) - 1 else "middle"
            button.setProperty("segment", place)
            button.clicked.connect(lambda _=False, v=value: self.chosen.emit(v))
            self.buttons[value] = button
            layout.addWidget(button)
        layout.addStretch()

    def set_value(self, value: str) -> None:
        if (button := self.buttons.get(value)) is not None:
            button.setChecked(True)
