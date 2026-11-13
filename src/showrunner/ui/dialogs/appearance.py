"""Appearance: theme mode, the three base colors, a live preview, and theme file import and export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from showrunner.app.options.serialization import WarningKind
from showrunner.app.settings.app_settings import ThemeMode
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.theme.manager import ThemeManager
from showrunner.ui.theme.qt_theme import build_stylesheet
from showrunner.ui.theme.theme_file import THEME_EXTENSION, load_theme_file, save_theme_file
from showrunner.ui.theme.tokens import DEFAULT_BASES, SIZES, Base, ColorSet, ink_on, resolve, with_base


class _Preview(QFrame):
    """A few roles of one color set, drawn with that set's own style sheet whatever the app's mode."""

    def __init__(self, color_set: ColorSet) -> None:
        super().__init__()
        self.color_set = color_set
        self.setProperty("role", "page")
        layout = QVBoxLayout(self)
        layout.setSpacing(SIZES["space_sm"])
        layout.setContentsMargins(*[SIZES["space_lg"]] * 4)
        title = QLabel(tr(f"appearance.preview.{color_set.value}"))
        title.setProperty("heading", True)
        layout.addWidget(title)
        layout.addWidget(QLabel(tr("appearance.sample.text")))
        for role in ("muted", "link", "notice", "danger", "selected"):
            label = QLabel(tr(f"appearance.sample.{role}"))
            label.setProperty("role", role)
            layout.addWidget(label)
        button = QPushButton(tr("appearance.sample.button"))
        button.setProperty("primary", True)
        layout.addWidget(button)

    def show_roles(self, roles: dict[str, str]) -> None:
        self.setStyleSheet(build_stylesheet(roles))


class AppearanceDialog(QDialog):
    """Every change applies to the whole app at once and is saved; there is nothing to confirm."""

    def __init__(self, theme: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(tr("appearance.title"))
        layout = QVBoxLayout(self)
        layout.setSpacing(SIZES["space_lg"])
        layout.setContentsMargins(*[SIZES["space_xl"]] * 4)

        form = QFormLayout()
        form.setSpacing(SIZES["space_md"])
        self._mode = QComboBox()
        for mode in ThemeMode:
            self._mode.addItem(tr(f"appearance.mode.{mode.value}"), mode)
        self._mode.setCurrentIndex(self._mode.findData(theme.mode))
        self._mode.currentIndexChanged.connect(self._on_mode_picked)
        form.addRow(tr("appearance.mode"), self._mode)

        self._swatches: dict[Base, QPushButton] = {}
        self._resets: dict[Base, QPushButton] = {}
        for base in Base:
            swatch = QPushButton()
            swatch.setMinimumWidth(SIZES["swatch_width"])
            swatch.setToolTip(tr(f"appearance.base.{base.value}.help"))
            swatch.clicked.connect(lambda _=False, b=base: self._pick(b))
            reset = QPushButton(tr("appearance.reset"))
            reset.setToolTip(tr("appearance.reset_tip", color=DEFAULT_BASES[base]))
            reset.clicked.connect(lambda _=False, b=base: self._set_base(b, None))
            row = QHBoxLayout()
            row.setSpacing(SIZES["space_md"])
            row.addWidget(swatch)
            row.addWidget(reset)
            row.addStretch()
            form.addRow(tr(f"appearance.base.{base.value}"), row)
            self._swatches[base] = swatch
            self._resets[base] = reset
        layout.addLayout(form)

        previews = QHBoxLayout()
        previews.setSpacing(SIZES["space_md"])
        self._previews = [_Preview(color_set) for color_set in ColorSet]
        for preview in self._previews:
            previews.addWidget(preview)
        layout.addLayout(previews)

        self._status = QLabel()
        self._status.setProperty("role", "muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.setSpacing(SIZES["space_md"])
        import_button = QPushButton(tr("appearance.import"))
        import_button.clicked.connect(self._import)
        export_button = QPushButton(tr("appearance.export"))
        export_button.clicked.connect(self._export)
        close_button = QPushButton(tr("common.close"))
        close_button.setProperty("primary", True)
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(import_button)
        buttons.addWidget(export_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        theme.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        colors = self._theme.colors
        for base in Base:
            hex_color = colors.base.get(base, DEFAULT_BASES[base])
            swatch = self._swatches[base]
            swatch.setText(hex_color)
            # The swatch shows the color being chosen, so its fill is that color rather than a role.
            swatch.setStyleSheet(f"background: {hex_color}; color: {ink_on(hex_color)}; border-color: {hex_color};")
            self._resets[base].setEnabled(base in colors.base)
        for preview in self._previews:
            preview.show_roles(resolve(colors, preview.color_set))

    def _on_mode_picked(self) -> None:
        # Qt hands item data back as a plain str, not as the enum it was given.
        self._theme.set_mode(ThemeMode(self._mode.currentData()))

    def _pick(self, base: Base) -> None:
        current = QColor(self._theme.colors.base.get(base, DEFAULT_BASES[base]))
        color = QColorDialog.getColor(current, self, tr(f"appearance.base.{base.value}"))
        if color.isValid():
            self._set_base(base, color.name())

    def _set_base(self, base: Base, hex_color: str | None) -> None:
        self._theme.set_colors(with_base(self._theme.colors, base, hex_color))

    def _file_filter(self) -> str:
        return tr("appearance.file_filter", pattern=f"*{THEME_EXTENSION}")

    def _import(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, tr("appearance.import_title"), "", self._file_filter())
        if not name:
            return
        loaded = load_theme_file(Path(name))
        if any(w.kind is WarningKind.UNREADABLE for w in loaded.warnings):
            QMessageBox.warning(self, tr("appearance.import_title"), tr("appearance.import_failed"))
            return
        self._theme.set_colors(loaded.value)
        if loaded.warnings:
            self._status.setText(tr("appearance.import_skipped", count=len(loaded.warnings)))
        else:
            self._status.setText(tr("appearance.imported"))

    def _export(self) -> None:
        suggested = tr("appearance.export_name") + THEME_EXTENSION
        name, _ = QFileDialog.getSaveFileName(self, tr("appearance.export_title"), suggested, self._file_filter())
        if not name:
            return
        path = Path(name)
        if not path.name.lower().endswith(".json"):
            path = path.with_name(path.name + THEME_EXTENSION)
        try:
            save_theme_file(path, self._theme.colors)
        except OSError as error:
            QMessageBox.warning(self, tr("appearance.export_title"), tr("appearance.export_failed", error=error))
            return
        self._status.setText(tr("appearance.exported", name=path.name))
