"""Application start-up for the graphical interface: the Qt Quick window."""

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

from showrunner import APP_NAME, __version__
from showrunner.app.profiles import registered  # noqa: F401  # registers every stage's options
from showrunner.app.settings.app_settings import load_settings
from showrunner.ui.i18n.catalog import set_language
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.window import WindowController

_log = logging.getLogger(__name__)


def main() -> int:
    # The video player draws through libmpv's OpenGL render API, so the window must use OpenGL rather than Direct3D,
    # the default on Windows. It has to be chosen before the first window exists.
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    # A QApplication rather than a QGuiApplication: the file and colour pickers are the platform's widget dialogs.
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    settings = load_settings()
    for warning in settings.warnings:
        _log.warning("Settings: %s at %s", warning.kind.value, warning.location)
    set_language(settings.value.ui_language)
    # The controller's Look sets the colour scheme (and so the title bar) from the theme the user chose.
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
