from PySide6.QtWidgets import QApplication

from showrunner.ui.i18n.catalog import tr
from showrunner.ui.main_window import MainWindow
from showrunner.ui.theme.manager import ThemeManager


def test_window_opens_and_closes(qapp: QApplication, theme: ThemeManager) -> None:
    window = MainWindow(theme)
    window.show()
    assert window.isVisible()
    assert window.windowTitle() == tr("main_window.title") == "Showrunner"
    assert window.close()
    assert not window.isVisible()
