from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from showrunner.app.settings.app_settings import RECENT_LIMIT, AppSettings, load_settings, save_settings, with_recent
from showrunner.app.storage.paths import HOME_ENV_VAR, data_dir, profiles_dir, settings_path
from showrunner.core.options.serialization import LoadWarning, WarningKind


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


def test_tool_paths_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = replace(AppSettings(), tool_paths={"tesseract": "D:/OCR/tesseract.exe"})
    save_settings(settings, path)
    assert json.loads(path.read_text(encoding="utf-8"))["tool_paths"] == {"tesseract": "D:/OCR/tesseract.exe"}
    assert load_settings(path).value == settings


def test_bad_tool_paths_fall_back_with_a_warning(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"format": 1, "tool_paths": {"tesseract": 3}}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.value.tool_paths == {}
    assert loaded.warnings == [LoadWarning(WarningKind.WRONG_TYPE, "settings.tool_paths")]


def test_recent_folders_put_the_newest_first_and_keep_a_few() -> None:
    first = datetime(2026, 1, 1, 12, 0)
    recent = with_recent({}, ["a", "b"], first)
    assert list(recent) == ["a", "b"]
    recent = with_recent(recent, ["b"], first + timedelta(days=1))
    assert list(recent) == ["b", "a"]
    assert recent["b"] == "2026-01-02T12:00:00"
    many = with_recent(recent, [str(n) for n in range(RECENT_LIMIT + 3)], first)
    assert len(many) == RECENT_LIMIT


def test_panel_sizes_and_recent_folders_are_saved(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(AppSettings(panel_sizes={"columns": "AAEC"}, recent_folders={"x": "2026-01-01T00:00:00"}), path)
    loaded = load_settings(path).value
    assert loaded.panel_sizes == {"columns": "AAEC"}
    assert loaded.recent_folders == {"x": "2026-01-01T00:00:00"}


def test_the_height_of_the_tracks_box_is_saved_and_an_old_file_without_it_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"format": 1, "active_profile": "Show Name"}), encoding="utf-8")
    old = load_settings(path)
    assert (old.value.overview_tracks_height, old.warnings) == (0, [])
    save_settings(replace(old.value, overview_tracks_height=312), path)
    assert load_settings(path).value.overview_tracks_height == 312
    assert json.loads(path.read_text(encoding="utf-8"))["overview_tracks_height"] == 312
    path.write_text(json.dumps({"format": 1, "overview_tracks_height": "tall"}), encoding="utf-8")
    wrong = load_settings(path)
    assert wrong.value.overview_tracks_height == 0
    assert wrong.warnings
