from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import Batches, BatchKey, BatchKind, Media
from showrunner.app.batches.choices import TrackChoice, TrackSignature, choose
from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.stages import TracksStage
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, Movie
from showrunner.core.track import AudioProperties, Track, TrackKind
from showrunner.stages.tracks import TrackPlan, TracksOptions, Verdict

COMMENTARY = Track(2, TrackKind.AUDIO, "A_AC3", Language("eng"), "Commentary", audio=AudioProperties(2))
TRACKS = (Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), "English", audio=AudioProperties(6)), COMMENTARY)


def episode(tmp_path: Path, number: int, season: int = 1, show: str = "Show Name") -> MediaItem:
    path = tmp_path / f"{show} - S{season:02}E{number:02}.mkv"
    path.write_bytes(b"matroska")
    return MediaItem(Episode(show, season, number), MediaFile(path, "matroska", tracks=TRACKS))


def movie(tmp_path: Path) -> MediaItem:
    path = tmp_path / "Movie Title (2016).mkv"
    path.write_bytes(b"matroska")
    return MediaItem(Movie("Movie Title", 2016), MediaFile(path, "matroska", tracks=TRACKS))


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    store = ProfileStore(tmp_path / "profiles")
    (tmp_path / "profiles").mkdir()
    return store


def drop_commentary(batches: Batches, key: BatchKey) -> None:
    copy = batches.copy(key)
    tracks = choose(copy.profile.for_stage("tracks"), TrackSignature.of(COMMENTARY), TrackChoice(Verdict.DROP))
    copy.set_options("tracks", tracks)


def test_the_keys_name_a_season_a_show_a_movie_and_a_selection(tmp_path: Path) -> None:
    first, second, other = episode(tmp_path, 1), episode(tmp_path, 2), episode(tmp_path, 1, season=2)
    assert BatchKey.of(first) == BatchKey.of(second) != BatchKey.of(other)
    assert BatchKey.of(first, whole_show=True) == BatchKey.of(other, whole_show=True)
    assert BatchKey.of(first).kind is BatchKind.SEASON
    assert BatchKey.of(movie(tmp_path)) == BatchKey(BatchKind.MOVIE, Media.MOVIES, "Movie Title", 2016)
    paths = [first.file.path, other.file.path]
    assert BatchKey.selection(paths, Media.EPISODES) == BatchKey.selection(paths[::-1], Media.EPISODES)


def test_a_choice_stays_in_the_batch_it_was_made_in(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    film, season = movie(tmp_path), episode(tmp_path, 1)
    drop_commentary(batches, BatchKey.of(film))
    assert batches.copy(BatchKey.of(film)).changed
    assert batches.profile(BatchKey.of(season)).for_stage("tracks") == TracksOptions()
    assert store.load(DEFAULT_PROFILE_NAME).value.for_stage("tracks") == TracksOptions()


def test_preview_plans_a_batch_with_its_own_unsaved_rules(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    items = [episode(tmp_path, 1), episode(tmp_path, 2)]
    key = BatchKey.of(items[0])
    drop_commentary(batches, key)
    result = preview(items, batches.profile(key), (TracksStage(),))
    for file in result.files:
        plan = file.plan_for("tracks")
        assert plan is not None
        assert isinstance(plan.plan, TrackPlan)
        assert [d.track.id for d in plan.plan.dropped] == [COMMENTARY.id]


def test_a_new_batch_starts_from_the_profile_last_used_for_its_media(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    first = BatchKey.of(episode(tmp_path, 1))
    drop_commentary(batches, first)
    batches.save_as(first, "Series")
    assert batches.last_used == {Media.EPISODES: "Series"}
    later = batches.copy(BatchKey.of(episode(tmp_path, 1, season=2)))
    assert later.name == "Series"
    assert not later.changed
    assert batches.copy(BatchKey.of(movie(tmp_path))).name == DEFAULT_PROFILE_NAME
    batches.switch(first, DEFAULT_PROFILE_NAME)
    assert batches.last_used[Media.EPISODES] == DEFAULT_PROFILE_NAME


def test_unsaved_edits_survive_a_restart(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    key = BatchKey.of(movie(tmp_path))
    drop_commentary(batches, key)
    selection = BatchKey.selection([tmp_path / "a.mkv"], Media.EPISODES)
    batches.copy(selection)
    data = json.loads(json.dumps(batches.to_json()))
    again = Batches.from_json(store, data)
    assert again.profile(key) == batches.profile(key)
    assert again.copy(key).changed
    assert again.copy(selection).name == DEFAULT_PROFILE_NAME
    assert not again.copy(selection).changed


def test_a_batch_whose_profile_is_gone_keeps_its_edits_and_bad_entries_are_skipped(
    tmp_path: Path, store: ProfileStore
) -> None:
    batches = Batches(store)
    key = BatchKey.of(movie(tmp_path))
    drop_commentary(batches, key)
    batches.save_as(key, "Movies")
    # An edit after the save, so the batch has unsaved changes when its profile goes.
    batches.copy(key).set_options("tracks", replace(batches.profile(key).for_stage("tracks"), flags_from_names=False))
    data = batches.to_json()
    store.delete("Movies")
    data["batches"].append({"key": {"kind": "nonsense"}, "profile": "X", "options": {}})
    data["batches"].append("not an entry")
    data["batches"].append({"key": data["batches"][0]["key"], "profile": 7, "options": {}})
    again = Batches.from_json(store, data)
    assert again.copy(key).name == DEFAULT_PROFILE_NAME
    assert again.profile(key).for_stage("tracks") == batches.profile(key).for_stage("tracks")
    assert again.last_used == {Media.MOVIES: "Movies"}
    assert Batches.from_json(store, "garbage").last_used == {}


def test_forgetting_a_batch_starts_it_again_from_its_profile(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    key = BatchKey.of(movie(tmp_path))
    drop_commentary(batches, key)
    batches.forget(key)
    assert not batches.copy(key).changed
