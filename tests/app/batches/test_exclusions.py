from __future__ import annotations

import json
from pathlib import Path

import pytest

from showrunner.app.batches.batch import Batches, BatchKey, BatchKind, Media
from showrunner.app.batches.exclusions import Exclusions
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.media import Episode, MediaFile, MediaItem, Movie

SHOW = BatchKey(BatchKind.SHOW, Media.EPISODES, "Show Name", 2020)
SEASON_1 = BatchKey(BatchKind.SEASON, Media.EPISODES, "Show Name", 2020, 1)
SEASON_2 = BatchKey(BatchKind.SEASON, Media.EPISODES, "Show Name", 2020, 2)
EPISODE = BatchKey(BatchKind.EPISODE, Media.EPISODES, "Show Name", 2020, 1, 3)
MOVIES = BatchKey.movies()
MOVIE = BatchKey(BatchKind.MOVIE, Media.MOVIES, "Movie Title", 2021)


GOOD = {
    "key": {"kind": "show", "media": "episodes", "title": "Show Name", "year": 2020, "season": None, "episode": None},
    "value": True,
}


def episode_item(season: int, number: int) -> MediaItem:
    path = Path(f"Show Name - S{season:02}E{number:02}.mkv")
    return MediaItem(Episode("Show Name", season, number, year=2020), MediaFile(path, "matroska"))


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    (tmp_path / "profiles").mkdir()
    return ProfileStore(tmp_path / "profiles")


def test_nothing_is_excluded_until_a_place_is() -> None:
    exclusions = Exclusions()
    assert not any(exclusions.excluded(key) for key in (SHOW, SEASON_1, EPISODE, MOVIES, MOVIE))


def test_a_show_excludes_everything_inside_it_and_nothing_beside_it() -> None:
    exclusions = Exclusions()
    exclusions.set(SHOW, True)
    assert all(exclusions.excluded(key) for key in (SHOW, SEASON_1, SEASON_2, EPISODE))
    assert not exclusions.excluded(MOVIES)
    assert not exclusions.excluded(MOVIE)


def test_the_movies_group_excludes_its_movies() -> None:
    exclusions = Exclusions()
    exclusions.set(MOVIES, True)
    assert exclusions.excluded(MOVIE)
    assert not exclusions.excluded(SHOW)


def test_a_place_inside_an_excluded_one_can_be_included_again_on_its_own() -> None:
    exclusions = Exclusions()
    exclusions.set(SHOW, True)
    exclusions.set(SEASON_1, False)
    assert exclusions.excluded(SHOW)
    assert exclusions.excluded(SEASON_2)
    assert not exclusions.excluded(SEASON_1)
    assert not exclusions.excluded(EPISODE)  # what lies inside the season follows the season's own value
    exclusions.set(EPISODE, True)  # and the nearest place decides again below it
    assert exclusions.excluded(EPISODE)
    assert not exclusions.excluded(SEASON_1)


def test_a_value_equal_to_what_the_place_receives_is_not_kept() -> None:
    exclusions = Exclusions()
    exclusions.set(SEASON_1, False)
    assert exclusions.values == {}
    exclusions.set(SHOW, True)
    exclusions.set(SEASON_1, True)
    assert exclusions.values == {SHOW: True}
    assert exclusions.own(SEASON_1) is None


def test_excluding_a_show_again_reaches_a_season_that_was_included_on_its_own() -> None:
    exclusions = Exclusions()
    exclusions.set(SHOW, True)
    exclusions.set(SEASON_1, False)
    exclusions.set(SHOW, False)  # the season's own value now equals what it receives, so it is dropped
    assert exclusions.values == {}
    exclusions.set(SHOW, True)
    assert exclusions.excluded(SEASON_1)


def test_files_are_excluded_by_their_place_in_the_show_row(store: ProfileStore) -> None:
    batches = Batches(store)
    items = [episode_item(1, 1), episode_item(1, 2), episode_item(2, 1)]
    batches.set_excluded(SEASON_1, True)
    assert batches.excluded_files(items, SHOW) == {items[0].file.path, items[1].file.path}
    batches.set_excluded(BatchKey.file(items[0]), False)
    assert batches.excluded_files(items, SHOW) == {items[1].file.path}
    # Titles that differ in case still name the show row's place.
    shouting = MediaItem(Episode("SHOW NAME", 1, 2, year=2020), items[1].file)
    assert batches.excluded_files([shouting], SHOW) == {items[1].file.path}


def test_a_movie_is_excluded_through_the_movies_group(store: ProfileStore) -> None:
    batches = Batches(store)
    item = MediaItem(Movie("Movie Title", 2021), MediaFile(Path("Movie Title (2021).mkv"), "matroska"))
    batches.set_excluded(MOVIES, True)
    assert batches.excluded_files([item], MOVIES) == {item.file.path}
    batches.set_excluded(BatchKey.file(item), False)
    assert batches.excluded_files([item], MOVIES) == set()


def test_exclusion_survives_a_restart(tmp_path: Path, store: ProfileStore) -> None:
    path = tmp_path / "workspace.json"
    batches = load_batches(store, path)
    batches.set_excluded(SHOW, True)
    batches.set_excluded(SEASON_2, False)
    batches.set_excluded(MOVIE, True)
    save_batches(batches, path)

    again = load_batches(store, path)
    assert again.is_excluded(SEASON_1)
    assert again.is_excluded(EPISODE)
    assert not again.is_excluded(SEASON_2)
    assert again.is_excluded(MOVIE)
    assert not again.is_excluded(MOVIES)
    assert again.exclusions.values == batches.exclusions.values


def test_a_workspace_saved_before_exclusion_loads_with_nothing_excluded(tmp_path: Path, store: ProfileStore) -> None:
    path = tmp_path / "workspace.json"
    path.write_text(
        json.dumps({"format": 2, "batches": {"last_used": {}, "batches": [], "places": []}}), encoding="utf-8"
    )
    batches = load_batches(store, path)
    assert batches.exclusions.values == {}
    assert not batches.is_excluded(SEASON_1)


@pytest.mark.parametrize(
    "entry",
    [None, 3, {}, {"key": {"kind": "show"}, "value": True}, {"key": GOOD["key"], "value": "yes"}, {"value": True}],
)
def test_an_unreadable_exclusion_is_skipped_and_the_rest_load(store: ProfileStore, entry: object) -> None:
    batches = Batches.from_json(store, {"excluded": [entry, GOOD]})
    assert batches.is_excluded(SEASON_1)
    assert len(batches.exclusions.values) == 1


def test_discarding_changes_leaves_exclusion_alone(store: ProfileStore) -> None:
    batches = Batches(store)
    batches.set_excluded(SEASON_1, True)
    batches.discard(SHOW)
    batches.discard(SEASON_1)
    assert batches.is_excluded(SEASON_1)
    assert not batches.discard_of(SEASON_1).anything
