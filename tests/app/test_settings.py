from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.options.serialization import LoadWarning, WarningKind
from showrunner.app.settings.app_settings import AppSettings, load_settings, save_settings
from showrunner.app.storage.paths import HOME_ENV_VAR, data_dir, profiles_dir, settings_path


def test_missing_file_gives_defaults_without_warnings(tmp_path: Path) -> None:
    loaded = load_settings(tmp_path / "settings.json")
    assert loaded.value == AppSettings()
    assert loaded.warnings == []


def test_round_trip_writes_only_changed_values(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = replace(AppSettings(), active_profile="Show Name", last_folders=["D:/tv"])
    save_settings(settings, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "format": 1,
        "active_profile": "Show Name",
        "last_folders": ["D:/tv"],
    }
    assert load_settings(path).value == settings


def test_save_leaves_no_temporary_file(tmp_path: Path) -> None:
    save_settings(AppSettings(window_geometry="abc"), tmp_path / "sub" / "settings.json")
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["settings.json"]


def test_bad_values_fall_back_with_warnings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"format": 1, "active_profile": 5, "window_geometry": "g", "future": 1}), encoding="utf-8"
    )
    loaded = load_settings(path)
    assert loaded.value == AppSettings(window_geometry="g")
    assert set(loaded.warnings) == {
        LoadWarning(WarningKind.WRONG_TYPE, "settings.active_profile"),
        LoadWarning(WarningKind.UNKNOWN_KEY, "settings.future"),
    }


@pytest.mark.parametrize("content", ["{broken", "[1]"])
def test_unreadable_file_gives_defaults_and_a_warning(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.value == AppSettings()
    assert [w.kind for w in loaded.warnings] == [WarningKind.UNREADABLE]


def test_home_override_moves_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))
    assert data_dir() == tmp_path
    assert profiles_dir() == tmp_path / "profiles"
    assert settings_path() == tmp_path / "settings.json"
    save_settings(AppSettings(active_profile="Show Name"))
    assert load_settings().value.active_profile == "Show Name"
    assert (tmp_path / "settings.json").is_file()


def test_default_location_is_the_platform_user_data_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOME_ENV_VAR, raising=False)
    assert data_dir().name == "Showrunner"
    assert data_dir().parent.name != "Showrunner"


def test_empty_home_variable_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOME_ENV_VAR, "")
    assert data_dir().name == "Showrunner"
