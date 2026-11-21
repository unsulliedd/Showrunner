"""Application start-up for the graphical interface: the Qt Quick window."""

import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

from showrunner import APP_NAME, __version__
from showrunner.app.profiles import registered  # noqa: F401  # registers every stage's options
from showrunner.app.settings.app_settings import load_settings
from showrunner.ui.i18n.catalog import set_language
from showrunner.ui.quick.collector import collect_on_gui_thread
from showrunner.ui.quick.engine import build_engine
from showrunner.ui.quick.window import WindowController

_log = logging.getLogger(__name__)

ICON = Path(__file__).parent / "resources" / "icon.ico"


def _set_taskbar_identity() -> None:
    """Gives the process its own app id so the Windows taskbar groups its windows under this icon, not Python's."""
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)


def main() -> int:
    # The video player draws through libmpv's OpenGL render API, so the window must use OpenGL rather than Direct3D,
    # the default on Windows. It has to be chosen before the first window exists.
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    _set_taskbar_identity()
    # A QApplication rather than a QGuiApplication: the file and colour pickers are the platform's widget dialogs.
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(ICON)))
    collect_on_gui_thread(app)
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
