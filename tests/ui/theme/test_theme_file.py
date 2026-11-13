from __future__ import annotations

import json
from pathlib import Path

import pytest

from showrunner.app.options.serialization import Loaded, LoadWarning, WarningKind
from showrunner.ui.theme.theme_file import MAX_THEME_BYTES, load_theme_file, save_theme_file
from showrunner.ui.theme.tokens import DEFAULT_BASES, Base, ColorSet, ThemeColors, with_base, with_role


def test_round_trip_writes_only_changes(tmp_path: Path) -> None:
    path = tmp_path / "mine.showrunner-theme.json"
    colors = with_role(with_base(ThemeColors(), Base.PRIMARY, "#7a1f1f"), ColorSet.DARK, "ink", "#ffffff")
    save_theme_file(path, colors)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "showrunner_theme": 1,
        "base": {"primary": "#7a1f1f"},
        "light": {},
        "dark": {"ink": "#ffffff"},
    }
    assert load_theme_file(path) == Loaded(colors)


def test_missing_file_gives_no_changes_silently(tmp_path: Path) -> None:
    loaded = load_theme_file(tmp_path / "none.json")
    assert loaded.value == ThemeColors()
    assert loaded.warnings == []


def test_bad_entries_are_skipped_and_the_rest_kept(tmp_path: Path) -> None:
    path = tmp_path / "theme.json"
    data = {
        "showrunner_theme": 1,
        "base": {"primary": "#ABC", "accent": DEFAULT_BASES[Base.ACCENT], "secondary": "blue", "other": "#000000"},
        "light": {"ink": "#000000", "surface": "#ffffff", "nope": "#111111", "muted": 5},
        "dark": [],
        "extra": {},
    }
    # A byte order mark in front of the JSON is accepted.
    path.write_text("﻿" + json.dumps(data), encoding="utf-8")
    loaded = load_theme_file(path)
    assert loaded.value == ThemeColors(base={Base.PRIMARY: "#aabbcc"}, light={"ink": "#000000"})
    assert set(loaded.warnings) == {
        LoadWarning(WarningKind.WRONG_TYPE, "base.secondary"),
        LoadWarning(WarningKind.UNKNOWN_KEY, "base.other"),
        LoadWarning(WarningKind.UNKNOWN_KEY, "light.nope"),
        LoadWarning(WarningKind.WRONG_TYPE, "light.muted"),
        LoadWarning(WarningKind.WRONG_TYPE, "dark"),
        LoadWarning(WarningKind.UNKNOWN_KEY, "extra"),
    }


def test_newer_format_is_read_with_a_warning(tmp_path: Path) -> None:
    path = tmp_path / "theme.json"
    path.write_text(json.dumps({"showrunner_theme": 9, "base": {"accent": "#010203"}}), encoding="utf-8")
    loaded = load_theme_file(path)
    assert loaded.value == ThemeColors(base={Base.ACCENT: "#010203"})
    assert loaded.warnings == [LoadWarning(WarningKind.NEWER_FORMAT, "showrunner_theme")]


@pytest.mark.parametrize("content", ["{broken", "[1]", '{"base": {}}', " " * (MAX_THEME_BYTES + 1)])
def test_a_file_that_is_not_a_theme_gives_no_changes(tmp_path: Path, content: str) -> None:
    path = tmp_path / "theme.json"
    path.write_text(content, encoding="utf-8")
    loaded = load_theme_file(path)
    assert loaded.value == ThemeColors()
    assert [w.kind for w in loaded.warnings] == [WarningKind.UNREADABLE]
