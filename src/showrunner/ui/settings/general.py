"""The General page: how the app starts. Saved as soon as it changes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QRadioButton, QVBoxLayout, QWidget

from showrunner.app.settings.app_settings import Startup, load_settings, save_settings
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.settings.page import SettingsPage, clear_layout, heading, label
from showrunner.ui.theme.tokens import SIZES

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Workspace:
    """What the next start would bring back, read from the main window as it is now."""

    folders: tuple[str, ...] = ()
    selected: str = ""
    library_width: int = 0
    details_width: int = 0


class GeneralPage(SettingsPage):
    def __init__(self, workspace: Callable[[], Workspace], parent: QWidget | None = None) -> None:
        super().__init__(tr("settings.page.general"), tr("settings.general.lead"), parent=parent)
        self._workspace = workspace
        columns = QHBoxLayout()
        columns.setSpacing(SIZES["space_xl"])
        left = QVBoxLayout()
        left.setSpacing(SIZES["space_sm"])
        left.addWidget(heading(tr("settings.general.startup")))
        self.choices = QButtonGroup(self)
        self.buttons: dict[Startup, QRadioButton] = {}
        for startup, key in ((Startup.LAST_WORKSPACE, "reopen"), (Startup.EMPTY, "empty")):
            button = QRadioButton(tr(f"settings.general.{key}"))
            self.choices.addButton(button)
            self.buttons[startup] = button
            left.addWidget(button)
            help_text = label(tr(f"settings.general.{key}_help"), "muted", wrap=True, size="sm")
            help_text.setContentsMargins(SIZES["space_xl"] + SIZES["space_md"], 0, 0, SIZES["space_md"])
            left.addWidget(help_text)
        left.addWidget(label(tr("settings.general.large_note"), "muted", wrap=True, size="sm"))
        left.addStretch()
        columns.addLayout(left, 3)

        panel = QFrame()
        panel.setProperty("role", "side_panel")
        side = QVBoxLayout(panel)
        side.setContentsMargins(*[SIZES["space_lg"]] * 4)
        side.setSpacing(SIZES["space_sm"])
        side.addWidget(heading(tr("settings.general.next_start")))
        side.addWidget(label(tr("settings.general.from_window"), "muted", size="sm"))
        self.facts = QGridLayout()
        self.facts.setHorizontalSpacing(SIZES["space_xl"])
        self.facts.setVerticalSpacing(SIZES["space_sm"])
        side.addLayout(self.facts)
        columns.addWidget(panel, 2, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(columns)
        self.body.addStretch()

        self.buttons[load_settings().value.startup].setChecked(True)
        self.choices.buttonToggled.connect(self._on_toggled)

    def _on_toggled(self, button: QRadioButton, checked: bool) -> None:
        if not checked:
            return
        startup = next(s for s, b in self.buttons.items() if b is button)
        try:
            save_settings(replace(load_settings().value, startup=startup))
        except OSError:
            _log.exception("Could not save the startup choice")
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.facts)
        if self.buttons[Startup.EMPTY].isChecked():
            self.facts.addWidget(label(tr("settings.general.nothing"), "muted", wrap=True), 0, 0, 1, 2)
            return
        space = self._workspace()
        rows = [
            ("folders", "\n".join(space.folders) or tr("common.none")),
            ("selected", space.selected or tr("common.none")),
            ("panes", tr("settings.general.pane_sizes", library=space.library_width, details=space.details_width)),
        ]
        for row, (key, value) in enumerate(rows):
            self.facts.addWidget(label(tr(f"settings.general.{key}"), "muted"), row, 0, Qt.AlignmentFlag.AlignTop)
            self.facts.addWidget(label(value, wrap=True), row, 1)
        self.facts.setColumnStretch(1, 1)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  # Qt's name
        super().showEvent(event)
        self.refresh()
