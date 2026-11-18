from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import BatchKey, BatchKind, Media
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.core.naming import EpisodeCodeFormat, NamingOptions, SpaceStyle
from showrunner.stages.tracks import KindTest, TrackMatch, TrackRule, TracksOptions

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


def test_a_file_of_two_episodes_is_placed_by_its_first_episode_and_keeps_its_choices_after_a_restart(
    tmp_path: Path, store: ProfileStore
) -> None:
    path = tmp_path / "workspace.json"
    ranged = MediaItem(
        Episode("Show Name", 1, 1, 2020, "Episode One", last_episode=2),
        MediaFile(tmp_path / "Show Name S01E01-E02.mkv", "matroska"),
    )
    single = replace(ranged, identity=replace(ranged.identity, last_episode=None))
    key = BatchKey.file(ranged)
    assert key == BatchKey.file(single) == BatchKey(BatchKind.EPISODE, Media.EPISODES, "Show Name", 2020, 1, 1)
    assert key.parent == SEASON

    batches = load_batches(store, path)
    batches.set_options(
        key, "naming", NamingOptions(audio_track_space=SpaceStyle.DOT, episode_code_format=EpisodeCodeFormat.CROSS)
    )
    save_batches(batches, path)

    saved = load_batches(store, path)
    naming = saved.profile(BatchKey.file(ranged)).for_stage("naming")
    assert (naming.audio_track_space, naming.episode_code_format) == (SpaceStyle.DOT, EpisodeCodeFormat.CROSS)
    # The season beside it is untouched.
    assert saved.profile(SEASON).for_stage("naming").audio_track_space is SpaceStyle.SPACE


def test_the_space_choice_passes_from_show_to_season_to_episode_and_the_nearest_place_decides(
    tmp_path: Path, store: ProfileStore
) -> None:
    show = BatchKey(BatchKind.SHOW, Media.EPISODES, "Show Name", 2020)
    episode = BatchKey(BatchKind.EPISODE, Media.EPISODES, "Show Name", 2020, 1, 1)
    other = BatchKey(BatchKind.SEASON, Media.EPISODES, "Show Name", 2020, 2)
    batches = load_batches(store, tmp_path / "workspace.json")

    def space(key: BatchKey) -> SpaceStyle:
        return batches.profile(key).for_stage("naming").audio_track_space

    batches.set_options(show, "naming", NamingOptions(audio_track_space=SpaceStyle.DOT))
    assert [space(k) for k in (show, SEASON, episode, other)] == [SpaceStyle.DOT] * 4

    batches.set_options(SEASON, "naming", NamingOptions(audio_track_space=SpaceStyle.DASH))
    assert [space(k) for k in (show, SEASON, episode, other)] == [
        SpaceStyle.DOT,
        SpaceStyle.DASH,
        SpaceStyle.DASH,
        SpaceStyle.DOT,
    ]

    batches.set_options(episode, "naming", NamingOptions(audio_track_space=SpaceStyle.SPACE))
    assert [space(k) for k in (show, SEASON, episode)] == [SpaceStyle.DOT, SpaceStyle.DASH, SpaceStyle.SPACE]


def test_a_language_choice_survives_a_restart_and_a_workspace_without_one_still_loads(
    tmp_path: Path, store: ProfileStore
) -> None:
    path = tmp_path / "workspace.json"
    batches = load_batches(store, path)
    copy = batches.copy(SEASON)
    rules = [TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["en"]), language="es-419", from_choice=True)]
    copy.set_options("tracks", replace(copy.profile.options["tracks"], rules=rules))
    save_batches(batches, path)
    assert load_batches(store, path).copy(SEASON).profile.for_stage("tracks").rules == rules

    # A file saved before rules had a language holds the rule without that key.
    data = json.loads(path.read_text(encoding="utf-8"))
    for place in data["batches"]["batches"]:
        for rule in place["options"]["stages"]["tracks"]["rules"]:
            del rule["language"]
    path.write_text(json.dumps(data), encoding="utf-8")
    (old,) = load_batches(store, path).copy(SEASON).profile.for_stage("tracks").rules
    assert (old.language, old.from_choice, old.match.languages) == ("", True, ["en"])


def test_the_videos_taken_out_of_the_list_survive_a_restart_and_an_old_file_loads_without_them(
    tmp_path: Path, store: ProfileStore
) -> None:
    path = tmp_path / "workspace.json"
    batches = load_batches(store, path)
    batches.removed |= {tmp_path / "Show" / "One.mkv", tmp_path / "Show" / "Two.mkv"}
    batches.set_excluded(SEASON, True)
    save_batches(batches, path)
    again = load_batches(store, path)
    assert again.removed == batches.removed
    assert again.is_excluded(SEASON)  # the exclusion is kept beside them

    data = json.loads(path.read_text(encoding="utf-8"))
    del data["batches"]["removed"]  # a file written before the list existed
    path.write_text(json.dumps(data), encoding="utf-8")
    old = load_batches(store, path)
    assert old.removed == set()
    assert old.is_excluded(SEASON)
