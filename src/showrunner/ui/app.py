"""Application start-up for the graphical interface: the Qt Quick window, or the Qt Widgets one with `--widgets`."""

import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

from showrunner import APP_NAME, __version__
from showrunner.app.profiles import registered  # noqa: F401  # registers every stage's options
from showrunner.app.settings.app_settings import ThemeMode, load_settings
from showrunner.app.storage.paths import theme_path
from showrunner.core.options.serialization import LoadWarning
from showrunner.ui.i18n.catalog import set_language
from showrunner.ui.main_window import MainWindow
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.window import WindowController
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.theme_file import load_theme_file

WIDGETS_FLAG = "--widgets"

_log = logging.getLogger(__name__)


def _log_warnings(what: str, warnings: list[LoadWarning]) -> None:
    for warning in warnings:
        _log.warning("%s: %s at %s", what, warning.kind.value, warning.location)


def _run_widgets(app: QApplication, mode: ThemeMode) -> int:
    colors = load_theme_file(theme_path())
    _log_warnings("Theme", colors.warnings)
    theme = ThemeManager(mode, colors.value)
    window = MainWindow(theme)
    window.show()
    # After the first paint, so the window is on screen while the folders are read and before any question.
    QTimer.singleShot(0, window.restore_workspace)
    QTimer.singleShot(0, window.offer_unfinished_jobs)
    return app.exec()


def _run_quick(app: QApplication) -> int:
    # The dark title bar goes with the dark theme, the one approved for this window.
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    controller = WindowController()
    engine = build_engine(controller)
    if not engine.rootObjects():
        return 1
    controller.start()
    QTimer.singleShot(0, controller.restore_workspace)
    code = app.exec()
    controller.stop_jobs()
    controller.save_workspace()
    return code


def main() -> int:
    widgets = WIDGETS_FLAG in sys.argv
    argv = [arg for arg in sys.argv if arg != WIDGETS_FLAG]
    if not widgets:
        # The video player draws through libmpv's OpenGL render API, so the window must use OpenGL rather than
        # Direct3D, the default on Windows. It has to be chosen before the first window exists.
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    settings = load_settings()
    _log_warnings("Settings", settings.warnings)
    set_language(settings.value.ui_language)
    return _run_widgets(app, settings.value.theme_mode) if widgets else _run_quick(app)
