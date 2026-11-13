"""The application's main window."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow

from showrunner.ui.dialogs.appearance import AppearanceDialog
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.tokens import SIZES


class MainWindow(QMainWindow):
    def __init__(self, theme: ThemeManager) -> None:
        super().__init__()
        self._theme = theme
        self.setWindowTitle(tr("main_window.title"))
        self.resize(SIZES["window_width"], SIZES["window_height"])
        view_menu = self.menuBar().addMenu(tr("main_window.menu.view"))
        self.appearance_action = view_menu.addAction(tr("main_window.action.appearance"))
        self.appearance_action.triggered.connect(self.open_appearance)

    def open_appearance(self) -> None:
        dialog = AppearanceDialog(self._theme, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.exec()
