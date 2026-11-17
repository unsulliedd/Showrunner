from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import BatchKey, BatchKind, Media
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.stages.tracks import KindTest, TrackMatch, TracksOptions

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


def test_a_track_order_survives_a_restart(tmp_path: Path, store: ProfileStore) -> None:
    path = tmp_path / "workspace.json"
    batches = load_batches(store, path)
    copy = batches.copy(SEASON)
    order = [TrackMatch(kind=KindTest.AUDIO, languages=["tr"]), TrackMatch(kind=KindTest.AUDIO, languages=["en"])]
    copy.set_options("tracks", replace(copy.profile.options["tracks"], order=order))
    save_batches(batches, path)

    again = load_batches(store, path).copy(SEASON)
    assert again.profile.for_stage("tracks").order == order
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == 2


def test_a_file_from_before_the_track_order_loads_without_one(tmp_path: Path, store: ProfileStore) -> None:
    """A workspace file written before tracks had an order: its choices load, and the order is the file's."""
    path = tmp_path / "workspace.json"
    rule = {"match": {"kind": "audio", "languages": ["tr"]}, "verdict": "keep", "default": "first", "from_choice": True}
    entry = {
        "key": {"kind": "season", "media": "episodes", "title": "Show Name", "year": 2020, "season": 1, "paths": []},
        "profile": DEFAULT_PROFILE_NAME,
        "options": {"format": 1, "stages": {"tracks": {"rules": [rule]}}},
    }
    path.write_text(json.dumps({"format": 1, "batches": {"last_used": {}, "batches": [entry]}}), encoding="utf-8")
    batches = load_batches(store, path)
    tracks = batches.profile(SEASON).for_stage("tracks")
    assert tracks.order == []
    # The season's choice is its own; its show, never opened, starts from the season's profile.
    assert not batches.copy(SEASON).changed
    assert batches.own(SEASON)["tracks"]["rules"] == tracks.rules
    assert [r.match.languages for r in tracks.rules] == [["tr"]]
