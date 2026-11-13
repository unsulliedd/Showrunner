"""Application start-up for the graphical interface."""

import sys

from PySide6.QtWidgets import QApplication

from showrunner import APP_NAME, __version__
from showrunner.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    return app.exec()
