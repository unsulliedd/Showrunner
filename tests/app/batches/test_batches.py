from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import Batches, BatchKey, BatchKind, Media
from showrunner.app.batches.choices import NO_CHOICE, TrackChoice, TrackSignature, choice_of, choose
from showrunner.app.jobs.preview import preview, preview_each
from showrunner.app.jobs.stages import TracksStage
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile, profile_to_json
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, Movie
from showrunner.core.track import AudioProperties, Track, TrackFlags, TrackKind
from showrunner.stages.tracks import KindTest, TrackMatch, TrackPlan, TrackRule, TracksOptions, Verdict

ENGLISH = Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), "English", audio=AudioProperties(6))
COMMENTARY = Track(2, TrackKind.AUDIO, "A_AC3", Language("eng"), "Commentary", audio=AudioProperties(2))
TURKISH = Track(3, TrackKind.AUDIO, "A_AC3", Language("tur"), "Türkçe", audio=AudioProperties(6))
TRACKS = (ENGLISH, COMMENTARY)
STAR = TrackChoice(Verdict.KEEP, default=True)


def episode(
    tmp_path: Path, number: int, season: int = 1, show: str = "Show Name", tracks: tuple[Track, ...] = TRACKS
) -> MediaItem:
    path = tmp_path / f"{show} - S{season:02}E{number:02}.mkv"
    path.write_bytes(b"matroska")
    return MediaItem(Episode(show, season, number), MediaFile(path, "matroska", tracks=tracks))


def movie(tmp_path: Path, title: str = "Movie Title") -> MediaItem:
    path = tmp_path / f"{title} (2016).mkv"
    path.write_bytes(b"matroska")
    return MediaItem(Movie(title, 2016), MediaFile(path, "matroska", tracks=TRACKS))


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    store = ProfileStore(tmp_path / "profiles")
    (tmp_path / "profiles").mkdir()
    return store


def pick(batches: Batches, key: BatchKey, track: Track, choice: TrackChoice) -> None:
    batches.set_options(key, "tracks", batches.with_choice(key, TrackSignature.of(track), choice))


def drop_commentary(batches: Batches, key: BatchKey) -> None:
    pick(batches, key, COMMENTARY, TrackChoice(Verdict.DROP))


def plan(batches: Batches, item: MediaItem) -> TrackPlan:
    result = preview([item], batches.profile(BatchKey.file(item)), (TracksStage(),)).files[0].plan_for("tracks")
    assert result is not None
    assert isinstance(result.plan, TrackPlan)
    return result.plan


def dropped(batches: Batches, item: MediaItem) -> list[int]:
    return [d.track.id for d in plan(batches, item).dropped]


def defaults(batches: Batches, item: MediaItem) -> list[int]:
    return [k.track.id for k in plan(batches, item).kept if k.flags.default]


def test_the_keys_name_each_place_and_its_parent(tmp_path: Path) -> None:
    first, second, other = episode(tmp_path, 1), episode(tmp_path, 2), episode(tmp_path, 1, season=2)
    assert BatchKey.of(first) == BatchKey.of(second) != BatchKey.of(other)
    assert BatchKey.of(first, whole_show=True) == BatchKey.of(other, whole_show=True)
    assert BatchKey.of(first).kind is BatchKind.SEASON
    assert BatchKey.of(movie(tmp_path)) == BatchKey(BatchKind.MOVIE, Media.MOVIES, "Movie Title", 2016)
    file = BatchKey.file(first)
    assert file == BatchKey(BatchKind.EPISODE, Media.EPISODES, "Show Name", None, 1, 1) != BatchKey.file(second)
    assert file.parent == BatchKey.of(first)
    assert file.parent.parent == file.root == BatchKey.of(first, whole_show=True)
    assert file.root.parent is None
    film = BatchKey.file(movie(tmp_path))
    assert film == BatchKey.of(movie(tmp_path))
    assert film.parent == film.root == BatchKey.movies()


def test_a_choice_on_a_show_reaches_its_seasons_and_episodes(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    first, other = episode(tmp_path, 1), episode(tmp_path, 1, season=2)
    drop_commentary(batches, BatchKey.of(first, whole_show=True))
    assert dropped(batches, first) == dropped(batches, other) == [COMMENTARY.id]
    assert choice_of(batches.profile(BatchKey.of(other)).for_stage("tracks"), TrackSignature.of(COMMENTARY)).verdict
    assert batches.own(BatchKey.of(first)) == {}
    # A movie lies in the Movies group, not in the show.
    assert dropped(batches, movie(tmp_path)) == []


def test_a_nearer_place_overrides_for_itself_only(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    first, second, other = episode(tmp_path, 1), episode(tmp_path, 2), episode(tmp_path, 1, season=2)
    show, season = BatchKey.of(first, whole_show=True), BatchKey.of(first)
    drop_commentary(batches, show)
    pick(batches, season, COMMENTARY, TrackChoice(Verdict.KEEP))
    assert dropped(batches, first) == dropped(batches, second) == []
    assert dropped(batches, other) == [COMMENTARY.id]
    # One episode of the season drops it again; its neighbour follows the season.
    drop_commentary(batches, BatchKey.file(second))
    assert (dropped(batches, first), dropped(batches, second)) == ([], [COMMENTARY.id])
    # A later choice on the show still reaches every place that did not choose otherwise.
    pick(batches, show, ENGLISH, STAR)
    assert defaults(batches, first) == defaults(batches, other) == [ENGLISH.id]


def test_a_nearer_place_can_take_back_what_it_receives(tmp_path: Path, store: ProfileStore) -> None:
    """Undoing a show's drop and star on a season: the season holds a choice of nothing, which hides the show's."""
    batches = Batches(store)
    first = episode(tmp_path, 1)
    show, season = BatchKey.of(first, whole_show=True), BatchKey.of(first)
    drop_commentary(batches, show)
    pick(batches, show, ENGLISH, STAR)
    loud = replace(first, file=replace(first.file, tracks=(replace(ENGLISH, flags=TrackFlags(default=False)),)))
    assert defaults(batches, loud) == [ENGLISH.id]
    pick(batches, season, COMMENTARY, NO_CHOICE)
    pick(batches, season, ENGLISH, NO_CHOICE)
    tracks = batches.profile(season).for_stage("tracks")
    assert [choice_of(tracks, TrackSignature.of(t)) for t in (COMMENTARY, ENGLISH)] == [NO_CHOICE, NO_CHOICE]
    assert dropped(batches, first) == []
    assert defaults(batches, loud) == []
    # Choosing what the show gives makes the season follow it again: its own rule goes.
    pick(batches, season, ENGLISH, STAR)
    pick(batches, season, COMMENTARY, TrackChoice(Verdict.DROP))
    assert batches.own(season) == {}
    assert dropped(batches, first) == [COMMENTARY.id]


def test_a_nearer_star_comes_first_and_the_one_received_is_its_fallback(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    both = episode(tmp_path, 1, tracks=(replace(ENGLISH, flags=TrackFlags(default=False)), TURKISH))
    english_only = episode(tmp_path, 2, tracks=(replace(ENGLISH, flags=TrackFlags(default=False)),))
    pick(batches, BatchKey.of(both, whole_show=True), ENGLISH, STAR)
    pick(batches, BatchKey.of(both), TURKISH, STAR)
    assert defaults(batches, both) == [TURKISH.id]
    assert defaults(batches, english_only) == [ENGLISH.id]


def test_the_nearest_order_wins_whole_and_an_empty_one_counts(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season = BatchKey.of(item, whole_show=True), BatchKey.of(item)
    turned = [TrackSignature.of(COMMENTARY).match(), TrackSignature.of(ENGLISH).match()]
    batches.set_options(show, "tracks", replace(batches.own_tracks(show), order=turned))
    assert [k.track.id for k in plan(batches, item).kept] == [COMMENTARY.id, ENGLISH.id]
    batches.set_options(season, "tracks", replace(batches.own_tracks(season), order=[]))
    assert batches.own(season) == {"tracks": {"order": []}}
    assert [k.track.id for k in plan(batches, item).kept] == [ENGLISH.id, COMMENTARY.id]
    batches.set_options(season, "tracks", replace(batches.own_tracks(season), order=turned))
    assert batches.own(season) == {}


def test_a_field_set_back_to_its_default_still_overrides(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season = BatchKey.of(item, whole_show=True), BatchKey.of(item)
    naming = batches.profile(show).for_stage("naming")
    batches.set_options(show, "naming", replace(naming, title_template="{show}"))
    batches.set_options(season, "naming", replace(naming, title_template=""))
    assert batches.profile(season).for_stage("naming").title_template == ""
    assert batches.profile(BatchKey.file(item)).for_stage("naming").title_template == ""
    assert batches.profile(BatchKey.of(episode(tmp_path, 1, season=2))).for_stage("naming").title_template == "{show}"


def test_forgetting_a_nearer_place_makes_it_follow_its_parent(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season = BatchKey.of(item, whole_show=True), BatchKey.of(item)
    drop_commentary(batches, show)
    pick(batches, season, COMMENTARY, TrackChoice(Verdict.KEEP))
    batches.forget(season)
    assert batches.own(season) == {}
    assert dropped(batches, item) == [COMMENTARY.id]
    batches.forget(show)
    assert not batches.copy(show).changed
    assert dropped(batches, item) == []


def test_files_that_set_nothing_share_their_seasons_options(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    items = [episode(tmp_path, n) for n in (1, 2, 3)] + [episode(tmp_path, 1, season=2)]
    drop_commentary(batches, BatchKey.file(items[2]))
    show = BatchKey.of(items[0], whole_show=True)
    profiles = batches.file_profiles(items, show)
    assert profiles[items[0].file.path] is profiles[items[1].file.path] is profiles[items[3].file.path]
    assert profiles[items[2].file.path] is not profiles[items[0].file.path]
    result = preview_each(items, profiles, (TracksStage(),))
    assert [f.item for f in result.files] == items
    assert len(result.profiles) == 2
    assert result.is_current(profiles, (TracksStage(),))
    assert not result.is_current(batches.file_profiles(items[:3], show), (TracksStage(),))
    planned = [f.plan_for("tracks") for f in result.files]
    assert [[d.track.id for d in p.plan.dropped] for p in planned if p and isinstance(p.plan, TrackPlan)] == [
        [],
        [],
        [COMMENTARY.id],
        [],
    ]


def test_each_rule_is_known_by_the_place_that_set_it(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season, file = BatchKey.of(item, whole_show=True), BatchKey.of(item), BatchKey.file(item)
    drop_commentary(batches, show)
    pick(batches, show, ENGLISH, STAR)
    pick(batches, season, ENGLISH, NO_CHOICE)
    assert batches.origins(season) == [season, show]
    assert batches.origins(file) == [season, show]
    pick(batches, file, COMMENTARY, TrackChoice(Verdict.KEEP))
    assert batches.origins(file) == [file, season]


def test_a_new_root_starts_from_the_profile_last_used_for_its_media(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    first = BatchKey.of(episode(tmp_path, 1), whole_show=True)
    drop_commentary(batches, first)
    batches.save_as(BatchKey.of(episode(tmp_path, 1)), "Series")
    assert batches.copy(first).name == "Series"
    assert batches.last_used == {Media.EPISODES: "Series"}
    later = batches.copy(BatchKey.of(episode(tmp_path, 1, show="Other Show")))
    assert later.name == "Series"
    assert not later.changed
    assert batches.copy(BatchKey.of(movie(tmp_path))).name == DEFAULT_PROFILE_NAME
    batches.switch(first, DEFAULT_PROFILE_NAME)
    assert batches.last_used[Media.EPISODES] == DEFAULT_PROFILE_NAME


def test_unsaved_edits_and_own_choices_survive_a_restart(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    film, item = BatchKey.of(movie(tmp_path)), episode(tmp_path, 1)
    drop_commentary(batches, BatchKey.movies())
    pick(batches, film, COMMENTARY, TrackChoice(Verdict.KEEP))
    pick(batches, BatchKey.file(item), ENGLISH, STAR)
    naming = batches.profile(BatchKey.of(item)).for_stage("naming")
    batches.set_options(BatchKey.of(item), "naming", replace(naming, title_template=""))
    data = json.loads(json.dumps(batches.to_json()))
    again = Batches.from_json(store, data)
    for key in (film, BatchKey.movies(), BatchKey.of(item), BatchKey.file(item)):
        assert again.profile(key) == batches.profile(key)
        assert again.own(key) == batches.own(key)
    assert again.copy(film).changed


def test_a_root_whose_profile_is_gone_keeps_its_edits_and_bad_entries_are_skipped(
    tmp_path: Path, store: ProfileStore
) -> None:
    batches = Batches(store)
    key = BatchKey.movies()
    drop_commentary(batches, key)
    batches.save_as(key, "Movies")
    # An edit after the save, so the root has unsaved changes when its profile goes.
    batches.set_options(key, "tracks", replace(batches.own_tracks(key), flags_from_names=False))
    data = batches.to_json()
    store.delete("Movies")
    data["batches"].append({"key": {"kind": "nonsense"}, "profile": "X", "options": {}})
    data["batches"].append("not an entry")
    data["batches"].append({"key": data["batches"][0]["key"], "profile": 7, "options": {}})
    data["places"] = [
        {"key": {"kind": "season", "media": "episodes", "season": "one"}, "own": {}},
        {"key": {"kind": "season", "media": "episodes", "title": "Show"}, "own": {"tracks": {"order": 5, "x": 1}}},
        "not an entry",
    ]
    again = Batches.from_json(store, data)
    assert again.copy(key).name == DEFAULT_PROFILE_NAME
    assert again.profile(key).for_stage("tracks") == batches.profile(key).for_stage("tracks")
    assert again.last_used == {Media.MOVIES: "Movies"}
    assert again.to_json()["places"] == []
    assert Batches.from_json(store, "garbage").last_used == {}


def test_batches_stored_whole_before_become_the_places_own_choices(tmp_path: Path, store: ProfileStore) -> None:
    """An old workspace held a whole profile per season, show, movie and selection."""
    store.save_as(store.load(DEFAULT_PROFILE_NAME).value, "Anime")
    first, lone = episode(tmp_path, 1), episode(tmp_path, 1, show="Lone Show")
    show_tracks = choose(TracksOptions(), TrackSignature.of(COMMENTARY), TrackChoice(Verdict.DROP))
    star = choose(show_tracks, TrackSignature.of(ENGLISH), STAR)
    keep = choose(TracksOptions(), TrackSignature.of(COMMENTARY), TrackChoice(Verdict.KEEP))

    def entry(key: BatchKey, profile: str, tracks: TracksOptions) -> dict[str, object]:
        options = profile_to_json(Profile.defaults(profile).with_options("tracks", tracks))
        data = {"kind": key.kind.value, "media": key.media.value, "title": key.title, "year": key.year}
        return {"key": {**data, "season": key.season, "paths": []}, "profile": profile, "options": options}

    selection = {"kind": "selection", "media": "movies", "title": "", "year": None, "season": None}
    data = {
        "last_used": {},
        "batches": [
            # A season ahead of its show, a season that followed another profile than its show, and one whose show
            # was never opened.
            entry(BatchKey.of(first), DEFAULT_PROFILE_NAME, star),
            entry(BatchKey.of(first, whole_show=True), DEFAULT_PROFILE_NAME, show_tracks),
            entry(BatchKey.of(episode(tmp_path, 1, season=2)), "Anime", TracksOptions()),
            entry(BatchKey.of(lone), "Anime", keep),
            {"key": {**selection, "paths": ["a.mkv"]}, "profile": DEFAULT_PROFILE_NAME, "options": {}},
            {"key": {**selection, "paths": ["b.mkv"]}, "profile": "Anime", "options": {}},
            entry(BatchKey.of(movie(tmp_path)), DEFAULT_PROFILE_NAME, keep),
        ],
    }
    batches = Batches.from_json(store, data)
    season = BatchKey.of(first)
    # The show's drop and the season's star, kept in the season's order ahead of what the show gives.
    assert batches.own(season) == {"tracks": {"rules": star.rules}}
    assert batches.profile(season).for_stage("tracks").rules == star.rules
    loud = replace(first, file=replace(first.file, tracks=(replace(ENGLISH, flags=TrackFlags(default=False)),)))
    assert (dropped(batches, first), defaults(batches, loud)) == ([COMMENTARY.id], [ENGLISH.id])
    # A season that set nothing keeps nothing of its own and follows its show.
    second = episode(tmp_path, 1, season=2)
    assert batches.own(BatchKey.of(second)) == {}
    assert dropped(batches, second) == [COMMENTARY.id]
    assert batches.copy(season).name == DEFAULT_PROFILE_NAME
    assert batches.copy(BatchKey.of(lone)).name == "Anime"
    assert batches.own(BatchKey.of(lone)) == {"tracks": {"rules": keep.rules}}
    assert batches.copy(BatchKey.movies()).name == "Anime"
    assert batches.own(BatchKey.of(movie(tmp_path))) == {"tracks": {"rules": keep.rules}}
    assert BatchKey.movies() in batches.following("Anime")


def test_an_old_season_left_as_its_profile_has_it_follows_its_show(tmp_path: Path, store: ProfileStore) -> None:
    """Every opened batch was stored, edited or not: a season on its show's profile keeps only what it changed, so the
    profile's own rules do not land ahead of the show's choices."""
    written = TrackRule(match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.KEEP)
    profile = store.load(DEFAULT_PROFILE_NAME).value
    store.save_as(profile.with_options("tracks", TracksOptions(rules=[written])), "Shows")
    item = episode(tmp_path, 1)
    show, season = BatchKey.of(item, whole_show=True), BatchKey.of(item)
    on_show = choose(TracksOptions(rules=[written]), TrackSignature.of(COMMENTARY), TrackChoice(Verdict.DROP))
    flags = replace(TracksOptions(rules=[written]), flags_from_names=False)

    def entry(key: BatchKey, tracks: TracksOptions) -> dict[str, object]:
        options = profile_to_json(Profile.defaults("Shows").with_options("tracks", tracks))
        data = {"kind": key.kind.value, "media": key.media.value, "title": key.title, "year": key.year}
        return {"key": {**data, "season": key.season, "paths": []}, "profile": "Shows", "options": options}

    second = BatchKey.of(episode(tmp_path, 1, season=2))
    data = {"batches": [entry(season, TracksOptions(rules=[written])), entry(show, on_show), entry(second, flags)]}
    batches = Batches.from_json(store, data)
    assert batches.own(season) == {}
    assert dropped(batches, item) == [COMMENTARY.id]
    assert batches.own(second) == {"tracks": {"flags_from_names": False}}


def test_every_file_under_a_show_row_follows_that_show(tmp_path: Path, store: ProfileStore) -> None:
    """The library lists a show's files under one row whatever year or case of title each file names."""
    batches = Batches(store)
    first = episode(tmp_path, 1)
    other = replace(episode(tmp_path, 2), identity=Episode("show name", 1, 2, 2020))
    show = BatchKey.of(first, whole_show=True)
    drop_commentary(batches, show)
    for profile in batches.file_profiles([first, other], show).values():
        assert [r.verdict for r in profile.for_stage("tracks").rules] == [Verdict.DROP]
    assert BatchKey.file(other).in_show(show).root == show
    assert BatchKey.file(movie(tmp_path)).in_show(show) == BatchKey.file(movie(tmp_path))


def test_a_renamed_profile_carries_the_roots_that_follow_it(tmp_path: Path, store: ProfileStore) -> None:
    store.save_as(store.load(DEFAULT_PROFILE_NAME).value, "Series")
    batches = Batches(store, {Media.EPISODES: "Series"})
    key = BatchKey.of(episode(tmp_path, 1))
    drop_commentary(batches, key.root)
    batches.rename_profile("Series", "Shows")
    assert batches.copy(key).name == "Shows"
    assert batches.copy(key).changed
    assert batches.last_used[Media.EPISODES] == "Shows"
    assert store.names() == [DEFAULT_PROFILE_NAME, "Shows"]


def test_a_deleted_profile_leaves_its_roots_their_choices_over_the_default(tmp_path: Path, store: ProfileStore) -> None:
    store.save_as(store.load(DEFAULT_PROFILE_NAME).value, "Series")
    batches = Batches(store, {Media.EPISODES: "Series"})
    key = BatchKey.of(episode(tmp_path, 1))
    drop_commentary(batches, key.root)
    rules = batches.profile(key).for_stage("tracks").rules
    batches.delete_profile("Series")
    assert batches.copy(key).name == DEFAULT_PROFILE_NAME
    assert batches.profile(key).for_stage("tracks").rules == rules
    assert Media.EPISODES not in batches.last_used


def test_an_edited_profile_reaches_its_roots_unless_they_changed_that_field(
    tmp_path: Path, store: ProfileStore
) -> None:
    store.save_as(store.load(DEFAULT_PROFILE_NAME).value, "Series")
    batches = Batches(store, {Media.EPISODES: "Series"})
    plain = BatchKey.of(episode(tmp_path, 1), whole_show=True)
    chosen = BatchKey.of(episode(tmp_path, 1, show="Other Show"), whole_show=True)
    batches.copy(plain)
    mux = batches.profile(chosen).for_stage("mux")
    batches.set_options(chosen, "mux", replace(mux, original="keep"))
    batches.edit_profile("Series", "mux", suffix=" new", original="recycle")
    assert store.load("Series").value.for_stage("mux").suffix == " new"
    assert batches.profile(plain).for_stage("mux").suffix == " new"
    assert not batches.copy(plain).changed
    # The root that chose to keep its originals keeps that unsaved choice, and takes the suffix.
    assert batches.profile(chosen).for_stage("mux").original == "keep"
    assert batches.profile(chosen).for_stage("mux").suffix == " new"
    assert batches.copy(chosen).changed
