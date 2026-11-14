"""Application start-up for the graphical interface."""

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from showrunner import APP_NAME, __version__
from showrunner.app.profiles import registered  # noqa: F401  # registers every stage's options
from showrunner.app.settings.app_settings import load_settings
from showrunner.app.storage.paths import theme_path
from showrunner.core.options.serialization import LoadWarning
from showrunner.ui.i18n.catalog import set_language
from showrunner.ui.main_window import MainWindow
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.theme_file import load_theme_file

_log = logging.getLogger(__name__)


def _log_warnings(what: str, warnings: list[LoadWarning]) -> None:
    for warning in warnings:
        _log.warning("%s: %s at %s", what, warning.kind.value, warning.location)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    settings = load_settings()
    _log_warnings("Settings", settings.warnings)
    set_language(settings.value.ui_language)
    colors = load_theme_file(theme_path())
    _log_warnings("Theme", colors.warnings)
    theme = ThemeManager(settings.value.theme_mode, colors.value)
    window = MainWindow(theme)
    window.show()
    # After the first paint, so the window is on screen while the folders are read and before any question.
    QTimer.singleShot(0, window.restore_workspace)
    QTimer.singleShot(0, window.offer_unfinished_jobs)
    return app.exec()
