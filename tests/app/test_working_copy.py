from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.errors import ProfileExistsError, ReadOnlyProfileError
from showrunner.app.profiles.store import ProfileStore
from showrunner.app.profiles.working import WorkingCopy
from showrunner.stages.tracks import TrackRule


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles")


def add_rule(copy: WorkingCopy) -> None:
    tracks = copy.profile.for_stage("tracks")
    copy.set_options("tracks", replace(tracks, rules=[*tracks.rules, TrackRule(label="Rule")]))


def test_edits_change_the_copy_and_not_the_file(store: ProfileStore) -> None:
    store.save_as(store.load("Default").value, "TV")
    copy = WorkingCopy(store, "TV")
    assert not copy.changed
    add_rule(copy)
    assert copy.changed
    assert store.load("TV").value.for_stage("tracks").rules == []
    copy.save()
    assert not copy.changed
    assert len(store.load("TV").value.for_stage("tracks").rules) == 1


def test_revert_goes_back_to_the_file(store: ProfileStore) -> None:
    copy = WorkingCopy(store, "Default")
    add_rule(copy)
    copy.revert()
    assert not copy.changed
    assert copy.profile.for_stage("tracks").rules == []


def test_default_is_read_only_and_saved_as_a_new_profile(store: ProfileStore) -> None:
    copy = WorkingCopy(store, "Default")
    assert copy.read_only
    add_rule(copy)
    with pytest.raises(ReadOnlyProfileError):
        copy.save()
    copy.save_as("Mine")
    assert (copy.name, copy.changed, copy.read_only) == ("Mine", False, False)
    assert len(store.load("Mine").value.for_stage("tracks").rules) == 1
    with pytest.raises(ProfileExistsError):
        copy.save_as("Mine")


def test_switching_drops_the_edits(store: ProfileStore) -> None:
    store.save_as(store.load("Default").value, "TV")
    copy = WorkingCopy(store, "Default")
    add_rule(copy)
    copy.switch("TV")
    assert (copy.name, copy.changed) == ("TV", False)


def test_a_rename_keeps_the_edits(store: ProfileStore) -> None:
    store.save_as(store.load("Default").value, "TV")
    copy = WorkingCopy(store, "TV")
    add_rule(copy)
    store.rename("TV", "Shows")
    copy.renamed("Shows")
    assert (copy.name, copy.changed) == ("Shows", True)
