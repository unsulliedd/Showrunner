"""The Programs page of the Widgets window, opened from the Qt Quick window until its own Settings dialog exists."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog, QFrame, QVBoxLayout

from showrunner.app.storage.paths import theme_path
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.settings.programs import ProgramsPage
from showrunner.ui.theme.qt_theme import build_font, build_palette, build_stylesheet
from showrunner.ui.theme.theme_file import load_theme_file
from showrunner.ui.theme.tokens import SIZES, ColorSet, resolve


def programs_dialog() -> tuple[QDialog, ProgramsPage]:
    """Every program with its download, locate and recheck actions, in the dark theme.

    The palette and style sheet are set on the dialog alone, so the application's palette, which QML controls read,
    stays as it is. The widget style is the application's: a widget's own style does not reach its children, and the
    QML window does not use widget styles.
    """
    QApplication.setStyle("Fusion")
    roles = resolve(load_theme_file(theme_path()).value, ColorSet.DARK)
    dialog = QDialog()
    dialog.setWindowTitle(tr("settings.page.programs"))
    dialog.setPalette(build_palette(roles))
    dialog.setFont(build_font())
    dialog.setStyleSheet(build_stylesheet(roles))
    dialog.resize(SIZES["dialog_width"], SIZES["dialog_height"])
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    # The style sheet draws a page's scroll area and rows inside a frame with this role, as the Settings window has.
    frame = QFrame(dialog)
    frame.setProperty("role", "page")
    outer.addWidget(frame)
    layout = QVBoxLayout(frame)
    margin = SIZES["space_xl"]
    layout.setContentsMargins(margin, margin, margin, margin)
    page = ProgramsPage(frame)
    layout.addWidget(page)
    return dialog, page


def run_programs_dialog(spec_id: str) -> None:
    """Show the dialog with `spec_id`'s row focused; returns when it closes, after stopping any download."""
    dialog, page = programs_dialog()
    row = page.rows.get(spec_id)
    if row is not None:
        row.setFocus()
    dialog.exec()
    page.stop()
