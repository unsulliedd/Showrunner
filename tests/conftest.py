import os

# Must be set before Qt loads a platform plugin: renders to memory, so tests need no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    # Qt allows one QApplication per process, so it is shared by every test.
    return QApplication.instance() or QApplication([])
