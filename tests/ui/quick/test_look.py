"""Appearance: the theme mode, base colours and density reach every engine's Theme, are saved, and the contrast
check names the text roles below 4.5:1."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from showrunner.app.settings.app_settings import Density, ThemeMode, load_settings
from showrunner.app.storage.paths import theme_path
from showrunner.ui.quick.engine import prepare
from showrunner.ui.quick.look import Look, contrast_problems, sizes_for
from showrunner.ui.quick.theme import Theme
from showrunner.ui.theme.theme_file import load_theme_file
from showrunner.ui.theme.tokens import COMPACT_SIZES, SIZES, Base, ColorSet, ThemeColors, resolve


def test_the_dark_theme_is_the_default_and_passes_the_contrast_check(qapp: QApplication) -> None:
    look = Look()
    assert look.mode == ThemeMode.DARK
    assert look.roles == resolve(ThemeColors(), ColorSet.DARK)
    assert look.contrast == []


def test_the_light_theme_shows_its_low_contrast_pair(qapp: QApplication) -> None:
    look = Look()
    look.set_mode("light")
    assert load_settings().value.theme_mode is ThemeMode.LIGHT
    assert look.color_set is ColorSet.LIGHT
    assert [(p["role"], p["on"]) for p in look.contrast] == [("control_ink", "control")]
    assert "3.8:1" in look.contrast[0]["text"]


def test_a_theme_follows_the_look_and_stops_with_its_engine(qapp: QApplication) -> None:
    prepare()
    look, theme = Look(), Theme()
    theme.follow(look)
    assert look.set_base(Base.PRIMARY.value, "#FF8FA8")
    assert theme.property("control") == QColor("#ff8fa8")
    assert load_theme_file(theme_path()).value.base == {Base.PRIMARY: "#ff8fa8"}
    look.set_density("compact")
    assert theme.property("list_row") == COMPACT_SIZES["list_row"]
    assert load_settings().value.density is Density.COMPACT
    theme.deleteLater()
    QApplication.sendPostedEvents()
    look.set_density("comfortable")  # a deleted Theme no longer hears the look


def test_a_bad_colour_is_refused_and_reset_returns_the_defaults(qapp: QApplication) -> None:
    look = Look()
    assert not look.set_base(Base.NEUTRAL.value, "dark grey")
    assert not look.changed_colors
    look.set_base(Base.ACCENT.value, "#abc")
    assert look.bases[2]["hex"] == "#AABBCC"
    look.reset_colors()
    assert not look.changed_colors
    assert look.message


def test_a_theme_file_imports_and_exports(qapp: QApplication, tmp_path: Path) -> None:
    look = Look()
    look.set_base(Base.PRIMARY.value, "#123456")
    look.export_to(tmp_path / "mine")
    exported = tmp_path / "mine.showrunner-theme.json"
    assert exported.is_file()
    look.reset_colors()
    look.import_from(exported)
    assert look.colors.base == {Base.PRIMARY: "#123456"}
    (tmp_path / "not.json").write_text("{}", encoding="utf-8")
    look.import_from(tmp_path / "not.json")
    assert look.colors.base == {Base.PRIMARY: "#123456"}
    assert "isn't" in look.message


def test_compact_sizes_change_only_rows_and_headers() -> None:
    assert sizes_for(Density.COMFORTABLE) == SIZES
    compact = sizes_for(Density.COMPACT)
    assert {key for key in SIZES if compact[key] != SIZES[key]} == set(COMPACT_SIZES)
    assert all(compact[key] < SIZES[key] for key in COMPACT_SIZES)


def test_the_contrast_check_lists_the_lowest_first() -> None:
    roles = resolve(ThemeColors(), ColorSet.DARK) | {"faint": "#22272f", "muted": "#555555"}
    problems = contrast_problems(roles)
    assert [p["role"] for p in problems][:2] == ["faint", "faint"]
    assert problems == sorted(problems, key=lambda p: p["ratio"])
