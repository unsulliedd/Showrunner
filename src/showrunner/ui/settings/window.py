"""The Settings window: a section list on the left and one page at a time on the right. Non-modal and made once,
so it stays open beside the main window and its live previews follow the main window's selection."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.storage.paths import data_dir
from showrunner.core.media import MediaItem
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.marks import dot_icon
from showrunner.ui.settings.appearance import AppearancePage
from showrunner.ui.settings.general import GeneralPage, Workspace
from showrunner.ui.settings.naming import NamingPage
from showrunner.ui.settings.page import SettingsPage, label, link_button
from showrunner.ui.settings.profiles import ProfilesPage
from showrunner.ui.settings.programs import ProgramsPage
from showrunner.ui.settings.session import ProfileSession
from showrunner.ui.settings.tracks import TracksPage
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES

PAGE_ROLE = Qt.ItemDataRole.UserRole + 1
# Pages in list order; None is the heading of the profile pages, "" the line under them.
_ORDER = ("general", "profiles", None, "naming", "tracks", "", "programs", "appearance")


class SettingsWindow(QDialog):
    """`programs_changed` passes on the Programs page's signal, for the main window's switches and empty state."""

    programs_changed = Signal()

    def __init__(
        self,
        theme: ThemeManager,
        session: ProfileSession,
        workspace: Callable[[], Workspace],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._session = session
        self.setProperty("role", "settings")
        self.setWindowTitle(tr("settings.title"))
        self.setModal(False)
        self.resize(SIZES["dialog_width"], SIZES["dialog_height"])

        self.general = GeneralPage(workspace)
        self.profiles = ProfilesPage(session)
        self.naming = NamingPage(session, theme)
        self.tracks = TracksPage(session, theme)
        self.programs = ProgramsPage()
        self.programs.programs_changed.connect(self.programs_changed)
        self.appearance = AppearancePage(theme)
        self.pages: dict[str, QWidget] = {
            "general": self.general,
            "profiles": self.profiles,
            "naming": self.naming,
            "tracks": self.tracks,
            "programs": self._wrapped(self.programs, "programs", tr("dependencies.intro")),
            "appearance": self._wrapped(self.appearance, "appearance", tr("settings.appearance.lead")),
        }

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SIZES["space_md"], SIZES["space_md"], SIZES["space_md"], SIZES["space_md"])
        layout.setSpacing(SIZES["space_md"])
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget()
        self.nav.setProperty("role", "settings_nav")
        self.nav.setFixedWidth(SIZES["settings_nav_width"])
        self.nav.setIconSize(QSize(SIZES["mark_size"] * 2, SIZES["mark_size"] * 2))
        self.stack = QStackedWidget()
        for key in _ORDER:
            item = QListWidgetItem()
            if key is None:
                self._heading = item
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            elif key == "":
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setSizeHint(QSize(0, SIZES["space_md"]))
            else:
                item.setText(tr(f"settings.page.{key}"))
                item.setData(PAGE_ROLE, key)
                self.stack.addWidget(self.pages[key])
            self.nav.addItem(item)
        self.nav.currentItemChanged.connect(self._on_nav)
        side.addWidget(self.nav, 1)
        side.addWidget(label(tr("settings.folder_note"), "muted", wrap=True, size="sm"))
        folder = link_button(tr("settings.open_folder"), self.open_folder)
        side.addWidget(folder, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(side)

        frame = QFrame()
        frame.setProperty("role", "page")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(self.stack)
        layout.addWidget(frame, 1)

        session.changed.connect(self.refresh_marks)
        self.open_page("general")
        self.refresh_marks()

    @staticmethod
    def _wrapped(content: QWidget, key: str, lead: str) -> SettingsPage:
        page = SettingsPage(tr(f"settings.page.{key}"), lead, scroll=False)
        page.body.addWidget(content, 1)
        return page

    def open_page(self, key: str) -> None:
        for row in range(self.nav.count()):
            if self.nav.item(row).data(PAGE_ROLE) == key:
                self.nav.setCurrentRow(row)

    def open_rule(self, index: int) -> None:
        self.open_page("tracks")
        self.tracks.select_rule(index)

    def current_page(self) -> str:
        item = self.nav.currentItem()
        return item.data(PAGE_ROLE) if item is not None else ""

    def set_item(self, item: MediaItem | None) -> None:
        """The file selected in the main window, for the live previews."""
        self.naming.set_item(item)
        self.tracks.set_item(item)

    def refresh_marks(self) -> None:
        self._heading.setText(tr("settings.in_profile", name=self._session.name))
        blocks = self._session.blocks()
        problems = {"naming": "metadata" in blocks, "tracks": self.tracks.has_problem()}
        dot = dot_icon(self._theme.roles["danger"])
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            key = item.data(PAGE_ROLE)
            if key in problems:
                item.setIcon(dot if problems[key] else QIcon())

    def _on_nav(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None and (key := current.data(PAGE_ROLE)):
            self.stack.setCurrentWidget(self.pages[key])

    @staticmethod
    def open_folder() -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802  # Qt's name
        self.programs.stop()
        super().closeEvent(event)
