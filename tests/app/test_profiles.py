from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from showrunner.app.profiles.errors import (
    InvalidProfileNameError,
    ProfileExistsError,
    ProfileNotFoundError,
    ReadOnlyProfileError,
    UnreadableProfileError,
)
from showrunner.app.profiles.profile import Profile, profile_from_json, profile_to_json
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.options.registry import OptionsRegistry
from showrunner.core.options.serialization import LoadWarning, WarningKind


@pytest.fixture
def store(tmp_path: Path, registry: OptionsRegistry) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles", registry)


def _custom(registry: OptionsRegistry, name: str, example: Any, **values: Any) -> Profile:
    return Profile.defaults(name, registry).with_options("example", example(**values))


# --- profile JSON ---


def test_default_profile_writes_no_stage_values(registry: OptionsRegistry) -> None:
    assert profile_to_json(Profile.defaults("p", registry), registry) == {"format": 1, "stages": {}}


def test_sparse_storage_and_round_trip(registry: OptionsRegistry, example: Any) -> None:
    profile = _custom(registry, "p", example, count=7, flag=True)
    data = profile_to_json(profile, registry)
    assert data == {"format": 1, "stages": {"example": {"flag": True, "count": 7}}}
    loaded = profile_from_json("p", data, registry)
    assert loaded.value == profile
    assert loaded.warnings == []


def test_stored_profile_follows_changed_defaults(registry: OptionsRegistry, example: Any) -> None:
    # A value left at its default is absent from the file, so it tracks whatever the default is later.
    data = profile_to_json(_custom(registry, "p", example, count=7), registry)
    assert "label" not in data["stages"]["example"]


def test_forgiving_load_reports_and_ignores_bad_entries(registry: OptionsRegistry, example: Any) -> None:
    data = {
        "format": 1,
        "stages": {"example": {"count": "many", "flag": True, "old": 1}, "removed": {"a": 1}},
    }
    loaded = profile_from_json("p", data, registry)
    assert loaded.value == _custom(registry, "p", example, flag=True)
    assert set(loaded.warnings) == {
        LoadWarning(WarningKind.WRONG_TYPE, "example.count"),
        LoadWarning(WarningKind.UNKNOWN_KEY, "example.old"),
        LoadWarning(WarningKind.UNKNOWN_STAGE, "removed"),
    }


def test_stage_entry_of_wrong_type_gives_defaults(registry: OptionsRegistry) -> None:
    loaded = profile_from_json("p", {"stages": {"example": [1]}}, registry)
    assert loaded.value == Profile.defaults("p", registry)
    assert loaded.warnings == [LoadWarning(WarningKind.WRONG_TYPE, "example")]


def test_newer_format_still_loads_with_a_warning(registry: OptionsRegistry) -> None:
    loaded = profile_from_json("p", {"format": 99, "stages": {}}, registry)
    assert loaded.warnings == [LoadWarning(WarningKind.NEWER_FORMAT, "format")]


def test_non_object_file_is_unreadable(registry: OptionsRegistry) -> None:
    with pytest.raises(UnreadableProfileError):
        profile_from_json("p", [1, 2], registry)


# --- store ---


def test_builtin_profiles_are_listed_first_and_load(store: ProfileStore, registry: OptionsRegistry) -> None:
    assert store.names() == ["Default"]
    assert store.load("default").value == Profile.defaults("Default", registry)


def test_builtin_profiles_are_read_only(store: ProfileStore, registry: OptionsRegistry) -> None:
    profile = Profile.defaults("Default", registry)
    with pytest.raises(ReadOnlyProfileError):
        store.save(profile)
    with pytest.raises(ReadOnlyProfileError):
        store.rename("Default", "Other")
    with pytest.raises(ReadOnlyProfileError):
        store.delete("Default")
    assert store.names() == ["Default"]


def test_editing_a_builtin_saves_a_copy_under_a_new_name(
    store: ProfileStore, registry: OptionsRegistry, example: Any
) -> None:
    edited = store.load("Default").value.with_options("example", example(count=1))
    saved = store.save_as(edited, "My movies")
    assert saved.name == "My movies"
    assert store.load("My movies").value == saved
    assert store.load("Default").value.for_stage("example").count == 3


def test_save_and_load_round_trip(store: ProfileStore, registry: OptionsRegistry, example: Any) -> None:
    profile = _custom(registry, "Show Name", example, label="sp")
    store.save(profile)
    assert store.names() == ["Default", "Show Name"]
    assert store.load("Show Name").value == profile


def test_atomic_save_leaves_no_temporary_file(store: ProfileStore, registry: OptionsRegistry, tmp_path: Path) -> None:
    store.save(Profile.defaults("a", registry))
    store.save(Profile.defaults("a", registry))
    assert [p.name for p in (tmp_path / "profiles").iterdir()] == ["a.json"]


def test_failed_save_keeps_old_file_and_removes_temporary(
    store: ProfileStore, registry: OptionsRegistry, example: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.save(_custom(registry, "a", example, count=1))

    def fail(*_: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr("showrunner.app.storage.files.os.replace", fail)
    with pytest.raises(OSError, match="disk"):
        store.save(_custom(registry, "a", example, count=2))
    monkeypatch.undo()
    assert [p.name for p in (tmp_path / "profiles").iterdir()] == ["a.json"]
    assert store.load("a").value.for_stage("example").count == 1


def test_duplicate(store: ProfileStore, registry: OptionsRegistry, example: Any) -> None:
    store.save(_custom(registry, "a", example, count=4))
    copy = store.duplicate("a", "b")
    assert copy.name == "b"
    assert store.load("b").value.for_stage("example").count == 4
    with pytest.raises(ProfileExistsError):
        store.duplicate("a", "B")


def test_rename(store: ProfileStore, registry: OptionsRegistry) -> None:
    store.save(Profile.defaults("a", registry))
    store.rename("a", "b")
    assert store.names() == ["Default", "b"]
    store.rename("b", "B")
    assert store.names()[-1] == "B"
    with pytest.raises(ProfileNotFoundError):
        store.rename("a", "c")


def test_rename_onto_existing_name_is_refused(store: ProfileStore, registry: OptionsRegistry) -> None:
    store.save(Profile.defaults("a", registry))
    store.save(Profile.defaults("b", registry))
    with pytest.raises(ProfileExistsError):
        store.rename("a", "b")
    with pytest.raises(ProfileExistsError):
        store.rename("a", "default")


def test_delete(store: ProfileStore, registry: OptionsRegistry) -> None:
    store.save(Profile.defaults("a", registry))
    store.delete("a")
    assert store.names() == ["Default"]
    with pytest.raises(ProfileNotFoundError):
        store.delete("a")
    with pytest.raises(ProfileNotFoundError):
        store.load("a")


def test_export_and_import(store: ProfileStore, registry: OptionsRegistry, example: Any, tmp_path: Path) -> None:
    store.save(_custom(registry, "a", example, count=8))
    target = tmp_path / "out" / "shared.json"
    store.export("a", target)
    imported = store.import_file(target)
    assert imported.value.name == "shared"
    assert imported.value.for_stage("example").count == 8
    other = store.import_file(target, name="renamed")
    assert other.value.name == "renamed"
    with pytest.raises(ProfileExistsError):
        store.import_file(target)


def test_export_of_builtin_profile(store: ProfileStore, tmp_path: Path) -> None:
    target = tmp_path / "default.json"
    store.export("Default", target)
    assert json.loads(target.read_text(encoding="utf-8")) == {"format": 1, "stages": {}}


def test_import_keeps_good_values_and_reports_the_rest(
    store: ProfileStore, registry: OptionsRegistry, tmp_path: Path
) -> None:
    source = tmp_path / "foreign.json"
    source.write_text(json.dumps({"format": 1, "stages": {"example": {"count": "x", "flag": True}}}), encoding="utf-8")
    imported = store.import_file(source)
    assert imported.value.for_stage("example").flag is True
    assert imported.warnings == [LoadWarning(WarningKind.WRONG_TYPE, "example.count")]


def test_import_of_a_file_that_is_not_json_fails_and_stores_nothing(store: ProfileStore, tmp_path: Path) -> None:
    source = tmp_path / "broken.json"
    source.write_text("{not json", encoding="utf-8")
    with pytest.raises(UnreadableProfileError):
        store.import_file(source)
    assert store.names() == ["Default"]


@pytest.mark.parametrize("name", ["", " a", "a ", "a/b", "a\\b", "a:b", "a.", "CON", "nul.txt", "x" * 101, "a\nb"])
def test_invalid_names_are_refused(store: ProfileStore, registry: OptionsRegistry, name: str) -> None:
    with pytest.raises(InvalidProfileNameError):
        store.save(Profile.defaults(name, registry))
