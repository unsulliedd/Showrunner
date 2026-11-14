from __future__ import annotations

from PySide6.QtWidgets import QApplication

from showrunner.ui.shell.loading import LoadingView, Spinner
from showrunner.ui.theme.manager import ThemeManager


def test_the_spinner_turns_only_while_visible(qapp: QApplication, theme: ThemeManager) -> None:
    spinner = Spinner()
    assert not spinner.spinning
    spinner.show()
    assert spinner.spinning
    start = spinner.angle
    spinner._turn()
    assert spinner.angle == (start + 30) % 360
    spinner.hide()
    assert not spinner.spinning


def test_the_view_shows_the_progress_it_is_given(qapp: QApplication, theme: ThemeManager) -> None:
    view = LoadingView()
    view.set_detail("Reading tracks 3 of 10")
    assert view.title.text() == "Reading the library"
    assert view.detail.text() == "Reading tracks 3 of 10"
