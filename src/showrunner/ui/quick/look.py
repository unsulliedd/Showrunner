"""How the window looks: the theme mode, the user's colour changes and the density, loaded at start and saved as
they change. Every engine's `Theme` shows what `Look` resolves, so a change repaints the window at once."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QColorDialog, QFileDialog

from showrunner.app.settings.app_settings import Density, ThemeMode, load_settings, save_settings
from showrunner.app.storage.paths import theme_path
from showrunner.core.options.serialization import WarningKind
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.theme.color import contrast, parse_hex
from showrunner.ui.theme.theme_file import THEME_EXTENSION, load_theme_file, save_theme_file
from showrunner.ui.theme.tokens import (
    COMPACT_SIZES,
    DEFAULT_BASES,
    SIZES,
    TEXT_CONTRAST,
    Base,
    ColorSet,
    ThemeColors,
    resolve,
    with_base,
)

_log = logging.getLogger(__name__)

# The bases Appearance offers, in its order: the ground, the control colour and the change colour. The fourth base
# (`secondary`) tints only the light set's selection and is left at its default.
SHOWN_BASES: tuple[Base, ...] = (Base.NEUTRAL, Base.PRIMARY, Base.ACCENT)
# The derived roles drawn under the bases.
SHOWN_ROLES: tuple[str, ...] = (
    "ground", "panel", "panel_3", "line", "ink", "muted", "faint", "select", "change", "drop", "add",
)  # fmt: skip
# Text and marks that must stay readable, each on the fills it is drawn on.
CONTRAST_PAIRS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ink", ("panel", "panel_2", "panel_3", "well")),
    ("muted", ("panel", "panel_2")),
    ("faint", ("panel", "panel_2")),
    ("change", ("panel", "panel_2")),
    ("drop", ("panel", "panel_2")),
    ("add", ("panel", "panel_2")),
    ("control_ink", ("control",)),
)


def contrast_problems(roles: dict[str, str]) -> list[dict[str, Any]]:
    """Every text role below 4.5:1 on a fill it is drawn on, lowest first."""
    found = [
        {"role": role, "on": fill, "ratio": round(contrast(roles[role], roles[fill]), 1)}
        for role, fills in CONTRAST_PAIRS
        for fill in fills
        if contrast(roles[role], roles[fill]) < TEXT_CONTRAST
    ]
    return sorted(found, key=lambda problem: problem["ratio"])


def sizes_for(density: Density) -> dict[str, int]:
    return {**SIZES, **COMPACT_SIZES} if density is Density.COMPACT else dict(SIZES)


class Look(QObject):
    """`changed` fires after the mode, a colour or the density changed, or Windows switched its scheme while the
    mode follows it."""

    changed = Signal()
    message_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        settings = load_settings().value
        loaded = load_theme_file(theme_path())
        for warning in loaded.warnings:
            _log.warning("Theme: %s at %s", warning.kind.value, warning.location)
        self._mode = settings.theme_mode
        self._density = settings.density
        self._colors = loaded.value
        self._message = ""
        self._tone = "add"
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(self._on_scheme)
        self._apply_scheme()

    # What the Theme objects show

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    @property
    def color_set(self) -> ColorSet:
        if self._mode is ThemeMode.SYSTEM:
            light = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light
            return ColorSet.LIGHT if light else ColorSet.DARK
        return ColorSet.LIGHT if self._mode is ThemeMode.LIGHT else ColorSet.DARK

    @property
    def roles(self) -> dict[str, str]:
        return resolve(self._colors, self.color_set)

    @property
    def sizes(self) -> dict[str, int]:
        return sizes_for(self._density)

    # Appearance reads these

    @Property(str, notify=changed)
    def mode(self) -> str:
        return self._mode.value

    @Property(str, notify=changed)
    def density(self) -> str:
        return self._density.value

    @Property(list, notify=changed)
    def bases(self) -> list[dict[str, Any]]:
        return [
            {"key": base.value, "hex": self._colors.base.get(base, DEFAULT_BASES[base]).upper()} for base in SHOWN_BASES
        ]

    @Property(list, notify=changed)
    def derived(self) -> list[dict[str, str]]:
        roles = self.roles
        return [{"key": key, "hex": roles[key]} for key in SHOWN_ROLES]

    @Property(list, notify=changed)
    def contrast(self) -> list[dict[str, Any]]:
        """The text roles of the shown set that fall below 4.5:1, worded; empty when every one passes."""
        return [
            {
                **problem,
                "text": tr("appearance.contrast_low", role=problem["role"], on=problem["on"], ratio=problem["ratio"]),
            }
            for problem in contrast_problems(self.roles)
        ]

    @Property(bool, notify=changed)
    def changed_colors(self) -> bool:
        return self._colors != ThemeColors()

    @Property(str, notify=message_changed)
    def message(self) -> str:
        return self._message

    @Property(str, notify=message_changed)
    def message_tone(self) -> str:
        return self._tone

    # Changes

    @Slot(str)
    def set_mode(self, mode: str) -> None:
        if mode not in set(ThemeMode) or mode == self._mode:
            return
        self._mode = ThemeMode(mode)
        self._remember(theme_mode=self._mode)
        self._apply_scheme()

    @Slot(str)
    def set_density(self, density: str) -> None:
        if density not in set(Density) or density == self._density:
            return
        self._density = Density(density)
        self._remember(density=self._density)
        self.changed.emit()

    @Slot(str, str, result=bool)
    def set_base(self, key: str, text: str) -> bool:
        """False when `text` is not a colour (`#rrggbb` or `#rgb`); the base then stays as it is."""
        hex_color = parse_hex(text)
        if key not in set(Base) or hex_color is None:
            return False
        self._set_colors(with_base(self._colors, Base(key), hex_color))
        return True

    @Slot(str)
    def pick_base(self, key: str) -> None:
        if key not in set(Base):
            return
        current = QColor(self._colors.base.get(Base(key), DEFAULT_BASES[Base(key)]))
        color = QColorDialog.getColor(
            current, None, tr("prefs.appearance.pick", name=tr(f"prefs.appearance.base.{key}"))
        )
        if color.isValid():
            self.set_base(key, color.name())

    @Slot()
    def reset_colors(self) -> None:
        self._set_colors(ThemeColors())
        self._say(tr("appearance.reset_done"))

    @Slot()
    def import_theme(self) -> None:
        name, _ = QFileDialog.getOpenFileName(None, tr("appearance.import_title"), "", self._file_filter())
        if name:
            self.import_from(Path(name))

    def import_from(self, path: Path) -> None:
        loaded = load_theme_file(path)
        if not path.is_file() or any(w.kind is WarningKind.UNREADABLE for w in loaded.warnings):
            self._say(tr("appearance.import_failed"), "drop")
            return
        self._set_colors(loaded.value)
        if loaded.warnings:
            self._say(tr("appearance.import_skipped", count=len(loaded.warnings)))
        else:
            self._say(tr("appearance.imported"))

    @Slot()
    def export_theme(self) -> None:
        suggested = tr("appearance.export_name") + THEME_EXTENSION
        name, _ = QFileDialog.getSaveFileName(None, tr("appearance.export_title"), suggested, self._file_filter())
        if name:
            self.export_to(Path(name))

    def export_to(self, path: Path) -> None:
        if not path.name.lower().endswith(".json"):
            path = path.with_name(path.name + THEME_EXTENSION)
        try:
            save_theme_file(path, self._colors)
        except OSError as error:
            self._say(tr("appearance.export_failed", error=error), "drop")
            return
        self._say(tr("appearance.exported", name=path.name))

    # Inside

    @staticmethod
    def _file_filter() -> str:
        return tr("appearance.file_filter", pattern=f"*{THEME_EXTENSION}")

    def _set_colors(self, colors: ThemeColors) -> None:
        if colors == self._colors:
            return
        self._colors = colors
        try:
            save_theme_file(theme_path(), colors)
        except OSError:
            _log.exception("Could not save the theme")
        self.changed.emit()

    def _remember(self, **changes: Any) -> None:
        try:
            save_settings(replace(load_settings().value, **changes))
        except OSError:
            _log.exception("Could not save the appearance")

    def _say(self, text: str, tone: str = "add") -> None:
        self._message, self._tone = text, tone
        self.message_changed.emit()

    def _apply_scheme(self) -> None:
        # Asking Qt for the scheme, rather than only picking the colour set, also turns the native title bar dark.
        hints = QGuiApplication.styleHints()
        if self._mode is ThemeMode.SYSTEM:
            hints.unsetColorScheme()
        else:
            hints.setColorScheme(Qt.ColorScheme.Light if self._mode is ThemeMode.LIGHT else Qt.ColorScheme.Dark)
        self.changed.emit()

    def _on_scheme(self, _scheme: Qt.ColorScheme) -> None:
        if self._mode is ThemeMode.SYSTEM:
            self.changed.emit()
