from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import BatchKey, BatchKind, Media
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.stages.tracks import TracksOptions

SEASON = BatchKey(BatchKind.SEASON, Media.EPISODES, "Show Name", 2020, 1)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    (tmp_path / "profiles").mkdir()
    return ProfileStore(tmp_path / "profiles")


def test_unsaved_edits_survive_a_restart(tmp_path: Path, store: ProfileStore) -> None:
    path = tmp_path / "workspace.json"
    batches = load_batches(store, path)
    copy = batches.copy(SEASON)
    edited = replace(copy.profile.options["tracks"], flags_from_names=False)
    copy.set_options("tracks", edited)
    save_batches(batches, path)

    again = load_batches(store, path).copy(SEASON)
    assert again.changed
    assert again.profile.options["tracks"] == edited
    assert again.name == DEFAULT_PROFILE_NAME
    assert isinstance(edited, TracksOptions)


@pytest.mark.parametrize("content", ["", "not json", "[1, 2]", '{"batches": 3}'])
def test_a_missing_or_unreadable_file_gives_no_batches(tmp_path: Path, store: ProfileStore, content: str) -> None:
    path = tmp_path / "workspace.json"
    if content:
        path.write_text(content, encoding="utf-8")
    batches = load_batches(store, path)
    assert batches.to_json()["batches"] == []
