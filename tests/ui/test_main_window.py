from PySide6.QtWidgets import QApplication

from showrunner import APP_NAME
from showrunner.ui.main_window import MainWindow


def test_window_opens_and_closes(qapp: QApplication) -> None:
    window = MainWindow()
    window.show()
    assert window.isVisible()
    assert window.windowTitle() == APP_NAME
    assert window.close()
    assert not window.isVisible()
