from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import Batches, BatchKey, BatchKind, Discard, Media
from showrunner.app.batches.choices import NO_CHOICE, TrackChoice, TrackSignature, choice_of, choose
from showrunner.app.batches.workspace import load_batches, save_batches
from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.jobs.preview import preview, preview_each
from showrunner.app.jobs.stages import TracksStage
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile, profile_to_json
from showrunner.app.profiles.store import DEFAULT_PROFILE_NAME, ProfileStore
from showrunner.core.language import Language
from showrunner.core.media import Episode, Extra, MediaFile, MediaItem, Movie
from showrunner.core.naming import CustomToken
from showrunner.core.track import AudioProperties, Track, TrackFlags, TrackKind
from showrunner.stages.mux.options import Original
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


def test_forgetting_a_root_returns_to_the_profile_it_follows_not_the_one_a_new_root_starts_from(
    tmp_path: Path, store: ProfileStore
) -> None:
    batches = Batches(store)
    show = BatchKey.of(episode(tmp_path, 1), whole_show=True)
    other = BatchKey.of(episode(tmp_path, 1, show="Other Show"), whole_show=True)
    batches.save_as(show, "Mine")
    drop_commentary(batches, show)
    batches.switch(other, DEFAULT_PROFILE_NAME)  # the profile a new show starts from is Default again
    batches.forget(show)
    assert batches.copy(show).name == "Mine"
    assert not batches.copy(show).changed


def test_discarding_a_folder_clears_it_and_every_place_inside_it(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    items = [episode(tmp_path, 1), episode(tmp_path, 2), episode(tmp_path, 1, season=2)]
    show, one, two = (BatchKey.of(items[0], whole_show=True), BatchKey.of(items[0]), BatchKey.of(items[2]))
    drop_commentary(batches, show)
    pick(batches, one, COMMENTARY, TrackChoice(Verdict.KEEP))  # overrides the show: one own rule
    pick(batches, BatchKey.file(items[1]), ENGLISH, TrackChoice(Verdict.DROP))
    pick(batches, two, ENGLISH, TrackChoice(Verdict.DROP))
    other = movie(tmp_path)
    drop_commentary(batches, BatchKey.file(other))
    assert batches.discard_of(one) == Discard(own=1, edited=False, inside=1, places=1)
    assert batches.discard_of(BatchKey.file(items[1])) == Discard(own=1, edited=False, inside=0, places=0)
    assert batches.discard_of(show) == Discard(own=0, edited=True, inside=3, places=3)
    batches.discard(one)
    assert batches.own(one) == {}
    assert batches.own(BatchKey.file(items[1])) == {}
    assert batches.own(two) != {}  # a sibling keeps its choices
    assert dropped(batches, items[0]) == [COMMENTARY.id]  # follows the show again
    batches.discard(show)
    assert not batches.discard_of(show).anything
    assert not batches.copy(show).changed
    assert dropped(batches, items[2]) == []
    assert dropped(batches, other) == [COMMENTARY.id]  # the Movies group's place is another folder


def test_discarding_the_movies_group_clears_its_movies(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = movie(tmp_path)
    drop_commentary(batches, BatchKey.file(item))
    batches.discard(BatchKey.movies())
    assert dropped(batches, item) == []
    assert not batches.discard_of(BatchKey.movies()).anything


def test_a_place_with_no_choices_of_its_own_has_nothing_to_discard(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    for key in (BatchKey.of(item, whole_show=True), BatchKey.of(item), BatchKey.file(item), BatchKey.movies()):
        assert not batches.discard_of(key).anything


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


def extra(tmp_path: Path, title: str = "Making Of", show: str = "Show Name") -> MediaItem:
    path = tmp_path / f"{show} - {title}.mkv"
    path.write_bytes(b"matroska")
    return MediaItem(Extra(show, title), MediaFile(path, "matroska", tracks=TRACKS))


def test_an_extra_is_a_place_inside_its_show_after_the_seasons(tmp_path: Path) -> None:
    item, other = extra(tmp_path), extra(tmp_path, "Bloopers")
    show = BatchKey.of(episode(tmp_path, 1), whole_show=True)
    group = BatchKey.of(item)
    file = BatchKey.file(item)
    assert BatchKey.of(item, whole_show=True) == show
    assert group == BatchKey(BatchKind.EXTRAS, Media.EPISODES, "Show Name")
    assert (
        file == BatchKey(BatchKind.EXTRA, Media.EPISODES, "Show Name", None, name="Making Of") != BatchKey.file(other)
    )
    assert file.parent == group == BatchKey.of(other)
    assert group.parent == file.root == show
    assert file.within(show)
    assert file.within(group)
    assert not file.within(BatchKey.of(episode(tmp_path, 1)))
    assert file.in_show(replace(show, title="SHOW NAME", year=2020)).year == 2020


def test_a_choice_on_a_show_reaches_its_extras_and_a_nearer_one_overrides_it(
    tmp_path: Path, store: ProfileStore
) -> None:
    batches = Batches(store)
    item, other = extra(tmp_path), extra(tmp_path, "Bloopers")
    drop_commentary(batches, BatchKey.of(item, whole_show=True))
    assert dropped(batches, item) == dropped(batches, other) == [COMMENTARY.id]
    pick(batches, BatchKey.of(item), COMMENTARY, TrackChoice(Verdict.KEEP))  # the group's, reaches each extra
    assert dropped(batches, item) == dropped(batches, other) == []
    drop_commentary(batches, BatchKey.file(other))
    assert dropped(batches, other) == [COMMENTARY.id]
    assert dropped(batches, item) == []
    assert dropped(batches, episode(tmp_path, 1)) == [COMMENTARY.id]  # the seasons are not in the group


def test_discarding_a_show_clears_the_choices_of_its_extras(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = extra(tmp_path)
    show, group, file = BatchKey.of(item, whole_show=True), BatchKey.of(item), BatchKey.file(item)
    drop_commentary(batches, file)
    assert batches.discard_of(file) == Discard(own=1, edited=False, inside=0, places=0)
    assert batches.discard_of(group) == Discard(own=0, edited=False, inside=1, places=1)
    assert batches.discard_of(show) == Discard(own=0, edited=False, inside=1, places=1)
    batches.discard(group)
    assert dropped(batches, item) == []
    drop_commentary(batches, file)
    batches.discard(file)
    assert not batches.discard_of(file).anything


def test_the_places_of_extras_survive_a_restart(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = extra(tmp_path)
    file = BatchKey.file(item)
    drop_commentary(batches, file)
    batches.set_excluded(BatchKey.of(item), True)
    path = tmp_path / "workspace.json"
    save_batches(batches, path)
    again = load_batches(store, path)
    assert again.own(file) == batches.own(file) != {}
    assert dropped(again, item) == [COMMENTARY.id]
    assert again.is_excluded(file)
    # A key stored before extras existed has no name and loads as it did.
    old = json.loads(path.read_text(encoding="utf-8"))
    for entry in (*old["batches"]["places"], *old["batches"]["excluded"]):
        del entry["key"]["name"]
    path.write_text(json.dumps(old), encoding="utf-8")
    assert load_batches(store, path).own(file) == {}


def hand_drop(batches: Batches, key: BatchKey) -> None:
    """A hand-written rule on a place: drop every audio track."""
    rule = TrackRule(match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.DROP)
    own = batches.own_tracks(key)
    batches.set_options(key, "tracks", replace(own, rules=[*own.rules, rule]))


def title(batches: Batches, key: BatchKey, template: str) -> None:
    naming = batches.profile(key).for_stage("naming")
    batches.set_options(key, "naming", replace(naming, title_template=template))


def test_a_kept_place_receives_nothing_from_above_and_keeps_its_own_choices(
    tmp_path: Path, store: ProfileStore
) -> None:
    batches = Batches(store)
    first, other = episode(tmp_path, 1), episode(tmp_path, 1, season=2)
    show, season = BatchKey.of(first, whole_show=True), BatchKey.of(first)
    hand_drop(batches, show)
    pick(batches, show, ENGLISH, STAR)
    title(batches, show, "{show}")
    assert batches.receives(season)
    batches.keep(season)
    assert batches.kept(season)
    assert dropped(batches, first) == []
    assert batches.profile(BatchKey.file(first)).for_stage("naming").title_template == ""
    assert dropped(batches, other) == [COMMENTARY.id]  # the star keeps English ahead of the hand-written drop
    # A later change on the show does not reach it either; its own choice after the keep does.
    title(batches, show, "{show} {episode}")
    drop_commentary(batches, season)
    assert batches.profile(season).for_stage("naming").title_template == ""
    assert dropped(batches, first) == [COMMENTARY.id]
    assert batches.origins(season) == [season]


def test_keeping_a_place_that_receives_nothing_or_a_root_stores_nothing(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    for key in (BatchKey.of(item, whole_show=True), BatchKey.of(item), BatchKey.movies()):
        batches.keep(key)
        assert not batches.kept(key)
        assert not batches.discard_of(key).anything


def test_discarding_a_kept_place_removes_the_keep_and_never_its_parents_choices(
    tmp_path: Path, store: ProfileStore
) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season = BatchKey.of(item, whole_show=True), BatchKey.of(item)
    drop_commentary(batches, show)
    batches.keep(BatchKey.file(item))
    assert batches.discard_of(BatchKey.file(item)) == Discard(own=0, edited=False, inside=0, places=0, kept=True)
    assert batches.discard_of(BatchKey.file(item)).only_kept
    assert batches.discard_of(season) == Discard(own=0, edited=False, inside=1, places=1)
    batches.discard(BatchKey.file(item))
    assert not batches.kept(BatchKey.file(item))
    assert dropped(batches, item) == [COMMENTARY.id]
    # From the season it goes too, as a place inside it; the show keeps its choice.
    batches.keep(BatchKey.file(item))
    batches.discard(season)
    assert not batches.kept(BatchKey.file(item))
    assert dropped(batches, item) == [COMMENTARY.id]


def test_a_keep_survives_a_restart(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    drop_commentary(batches, BatchKey.of(item, whole_show=True))
    batches.keep(BatchKey.of(item))
    data = json.loads(json.dumps(batches.to_json()))
    data["kept"].append({"kind": "nonsense"})
    again = Batches.from_json(store, data)
    assert again.kept(BatchKey.of(item))
    assert dropped(again, item) == []


def test_each_field_is_known_by_the_place_that_set_it(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season, file = BatchKey.of(item, whole_show=True), BatchKey.of(item), BatchKey.file(item)
    origin = "naming", "title_template"
    assert [batches.field_origin(key, *origin) for key in (show, season, file)] == [None, None, None]
    title(batches, show, "{show}")
    assert [batches.field_origin(key, *origin) for key in (show, season, file)] == [show, show, show]
    # "As it is" set on the season is a value of its own, which the episode receives from it.
    title(batches, season, "")
    assert [batches.field_origin(key, *origin) for key in (season, file)] == [season, season]
    batches.forget(season)
    batches.keep(season)
    assert [batches.field_origin(key, *origin) for key in (season, file)] == [season, season]
    # A field nothing above sets stays unmarked in a kept place.
    assert batches.field_origin(season, "metadata", "untagged_language") is None


def test_normalizing_drops_what_a_place_sets_to_what_it_now_receives(tmp_path: Path, store: ProfileStore) -> None:
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season, file = BatchKey.of(item, whole_show=True), BatchKey.of(item), BatchKey.file(item)
    title(batches, season, "{show}")
    drop_commentary(batches, file)
    # The show comes to say the same; the values stay until the places are normalized.
    title(batches, show, "{show}")
    drop_commentary(batches, show)
    assert batches.own(season)
    assert batches.own(file)
    batches.normalize(show)
    assert batches.own(season) == batches.own(file) == {}
    assert dropped(batches, item) == [COMMENTARY.id]
    # Now the season follows the show again, and a later change reaches it.
    title(batches, show, "{episode}")
    assert batches.profile(season).for_stage("naming").title_template == "{episode}"


def test_normalizing_keeps_a_repeated_choice_whose_going_would_change_the_plan(
    tmp_path: Path, store: ProfileStore
) -> None:
    """Without its own choice the received one comes after the place's other rules, which would then decide first."""
    batches = Batches(store)
    quiet = (replace(ENGLISH, flags=TrackFlags(default=False)), COMMENTARY, TURKISH)
    item = episode(tmp_path, 1, tracks=quiet)
    show, season = BatchKey.of(item, whole_show=True), BatchKey.of(item)
    # A second star is the fallback of the first; the show comes to give the first one.
    pick(batches, season, ENGLISH, STAR)
    pick(batches, season, TURKISH, STAR)
    pick(batches, show, ENGLISH, STAR)
    # A drop ahead of a hand-written keep; the show comes to drop the same tracks.
    drop_commentary(batches, season)
    rule = TrackRule(match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.KEEP)
    own = batches.own_tracks(season)
    batches.set_options(season, "tracks", replace(own, rules=[*own.rules, rule]))
    drop_commentary(batches, show)
    before = (defaults(batches, item), dropped(batches, item))
    assert before == ([ENGLISH.id], [COMMENTARY.id])
    batches.normalize(show)
    assert (defaults(batches, item), dropped(batches, item)) == before


def test_a_kept_place_keeps_what_only_says_how_so_its_own_template_works(tmp_path: Path, store: ProfileStore) -> None:
    """Custom tokens, value maps and where originals go change nothing alone: they still come from above."""
    batches = Batches(store)
    item = episode(tmp_path, 1)
    show, season = BatchKey.of(item, whole_show=True), BatchKey.of(item)
    naming = batches.profile(show).for_stage("naming")
    tokens = [CustomToken("tag", text="Remastered")]
    batches.set_options(show, "naming", replace(naming, title_template="{tag}", custom_tokens=tokens))
    mux = batches.profile(show).for_stage("mux")
    batches.set_options(show, "mux", replace(mux, original=Original.KEEP))
    batches.keep(season)
    kept = batches.profile(season)
    assert kept.for_stage("naming").title_template == ""
    assert kept.for_stage("naming").custom_tokens == tokens
    assert kept.for_stage("mux").original is Original.KEEP
    assert not batches.receives(season)
    # Only the cancelled field reads as the kept place's own; the tokens are still the show's.
    assert batches.field_origin(season, "naming", "title_template") == season
    assert batches.field_origin(season, "naming", "custom_tokens") == show
    # The season's own template uses the show's token and is not blocked.
    title(batches, season, "{show} {tag}")
    assert "metadata" not in blocked_stages(batches.profile(season))
