"""The application's main window."""

from PySide6.QtWidgets import QMainWindow

from showrunner import APP_NAME

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)
