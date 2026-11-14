"""The active theme: mode and color changes, applied to the running application and saved."""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from showrunner.app.settings.app_settings import ThemeMode, load_settings, save_settings
from showrunner.app.storage.paths import theme_path
from showrunner.ui.theme.qt_theme import build_font, build_palette, build_stylesheet
from showrunner.ui.theme.theme_file import save_theme_file
from showrunner.ui.theme.tokens import ColorSet, ThemeColors, resolve

_log = logging.getLogger(__name__)

_SCHEMES = {ThemeMode.LIGHT: Qt.ColorScheme.Light, ThemeMode.DARK: Qt.ColorScheme.Dark}


class ThemeManager(QObject):
    """Owns the theme of the one QApplication. `changed` fires after every re-apply."""

    changed = Signal()

    def __init__(self, mode: ThemeMode, colors: ThemeColors, parent: QObject | None = None) -> None:
        super().__init__(parent)
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("ThemeManager needs a QApplication")
        self._app = app
        self._mode = mode
        self._colors = colors
        self._roles: dict[str, str] = {}
        # The native Windows 11 style draws its own colors and ignores most of the palette; Fusion uses it all.
        app.setStyle("Fusion")
        app.setFont(build_font())
        app.styleHints().colorSchemeChanged.connect(self._on_scheme_changed)
        self._apply_mode()

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    @property
    def color_set(self) -> ColorSet:
        if self._mode is ThemeMode.SYSTEM:
            dark = self._app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        else:
            dark = self._mode is ThemeMode.DARK
        return ColorSet.DARK if dark else ColorSet.LIGHT

    @property
    def roles(self) -> dict[str, str]:
        """The resolved color of every role in the active set, for widgets that paint themselves."""
        return self._roles

    def set_mode(self, mode: ThemeMode) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        try:
            save_settings(replace(load_settings().value, theme_mode=mode))
        except OSError:
            _log.exception("Could not save the theme mode")
        self._apply_mode()

    def set_colors(self, colors: ThemeColors) -> None:
        if colors == self._colors:
            return
        self._colors = colors
        try:
            save_theme_file(theme_path(), colors)
        except OSError:
            _log.exception("Could not save the theme")
        self.apply()

    def apply(self) -> None:
        roles = self._roles = resolve(self._colors, self.color_set)
        self._app.setPalette(build_palette(roles))
        self._app.setStyleSheet(build_stylesheet(roles))
        self.changed.emit()

    def _apply_mode(self) -> None:
        # Asking Qt for the scheme, rather than only picking the color set, also turns the native title bar dark.
        hints = self._app.styleHints()
        if self._mode is ThemeMode.SYSTEM:
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(_SCHEMES[self._mode])
        self.apply()

    def _on_scheme_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self._mode is ThemeMode.SYSTEM:
            self.apply()
