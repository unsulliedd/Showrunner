"""Choices made on one name of a chip: a narrow rule by name, ahead of the chip's own choice, that follows the places
(a nearer place's rule hides the parent's on the same name, a nearer chip choice decides first)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import Batches, BatchKey
from showrunner.app.batches.choices import (
    NO_CHOICE,
    TrackChoice,
    TrackSignature,
    choice_of,
    choose,
    layered_rules,
    name_of_rule,
    named,
)
from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.stages import TracksStage
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.core.track import AudioProperties, Track, TrackKind
from showrunner.stages.tracks import FlagShape, TrackPlan, TracksOptions, Verdict

DIRECTOR = "Commentary with the director"
CAST = "Commentary with the cast (2020) [HD]"
STAR = TrackChoice(Verdict.KEEP, default=True)
DROP = TrackChoice(Verdict.DROP)
KEEP = TrackChoice(Verdict.KEEP)


def audio(track_id: int, language: str, name: str, channels: int) -> Track:
    return Track(track_id, TrackKind.AUDIO, "A_AC3", Language(language), name, audio=AudioProperties(channels))


ENGLISH = audio(1, "eng", "English", 6)
TURKISH = audio(2, "tur", "Turkish", 6)


def commentary(name: str) -> Track:
    return audio(3, "eng", name, 2)


# One signature for every commentary, whatever its name: the chip these names sit under.
CHIP = TrackSignature.of(commentary(DIRECTOR))


def episode(tmp_path: Path, number: int, name: str, season: int = 1) -> MediaItem:
    path = tmp_path / f"Show Name - S{season:02}E{number:02}.mkv"
    path.write_bytes(b"matroska")
    tracks = (ENGLISH, TURKISH, commentary(name))
    return MediaItem(Episode("Show Name", season, number), MediaFile(path, "matroska", tracks=tracks))


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    store = ProfileStore(tmp_path / "profiles")
    (tmp_path / "profiles").mkdir()
    return store


@pytest.fixture
def director(tmp_path: Path) -> MediaItem:
    return episode(tmp_path, 1, DIRECTOR)


@pytest.fixture
def cast(tmp_path: Path) -> MediaItem:
    return episode(tmp_path, 2, CAST.upper())  # the name test ignores case


def pick(batches: Batches, key: BatchKey, signature: TrackSignature, choice: TrackChoice, lead: bool = False) -> None:
    batches.set_options(key, "tracks", batches.with_choice(key, signature, choice, lead))


def dropped(batches: Batches, item: MediaItem) -> list[int]:
    result = preview([item], batches.profile(BatchKey.file(item)), (TracksStage(),)).files[0].plan_for("tracks")
    assert result is not None
    assert isinstance(result.plan, TrackPlan)
    return [d.track.id for d in result.plan.dropped]


def defaults(batches: Batches, item: MediaItem) -> list[int]:
    result = preview([item], batches.profile(BatchKey.file(item)), (TracksStage(),)).files[0].plan_for("tracks")
    assert result is not None
    assert isinstance(result.plan, TrackPlan)
    return [k.track.id for k in result.plan.kept if k.flags.default]


def test_a_name_rule_leads_the_chip_s_own_choice_and_reads_back_as_its_name() -> None:
    options = choose(TracksOptions(), CHIP, DROP)
    options = choose(options, named(CHIP, CAST), KEEP, lead=True)
    chip_rule = options.rules[1]
    name_rule = options.rules[0]
    assert (name_rule.from_choice, name_rule.verdict, name_rule.default, name_rule.forced) == (
        True,
        Verdict.KEEP,
        FlagShape.LEAVE,
        FlagShape.LEAVE,
    )
    assert chip_rule.verdict is Verdict.DROP
    # The two choices do not find each other's rule.
    assert choice_of(options, CHIP).verdict is Verdict.DROP
    assert choice_of(options, named(CHIP, CAST)).verdict is Verdict.KEEP
    assert choice_of(options, named(CHIP, DIRECTOR)) == NO_CHOICE
    # The name, with its brackets and spaces, comes back from the rule.
    assert name_of_rule(name_rule, [CHIP]) == named(CHIP, CAST)
    assert name_of_rule(chip_rule, [CHIP]) is None
    # A chip choice made after the name rule still goes behind it.
    again = choose(choose(TracksOptions(), named(CHIP, CAST), KEEP, lead=True), CHIP, DROP)
    assert [r.verdict for r in again.rules] == [Verdict.KEEP, Verdict.DROP]


def test_a_name_goes_back_to_following_the_chip_when_its_choice_is_taken_back() -> None:
    options = choose(choose(TracksOptions(), CHIP, DROP), named(CHIP, CAST), KEEP, lead=True)
    back = choose(options, named(CHIP, CAST), TrackChoice(Verdict.PASS), lead=True)
    assert [r.verdict for r in back.rules] == [Verdict.DROP]


def test_a_rule_by_name_decides_for_that_name_only(
    tmp_path: Path, store: ProfileStore, director: MediaItem, cast: MediaItem
) -> None:
    batches = Batches(store)
    show = BatchKey.of(director, whole_show=True)
    pick(batches, show, named(CHIP, DIRECTOR), DROP, lead=True)
    assert dropped(batches, director) == [3]
    assert dropped(batches, cast) == []
    # Dropping the chip afterwards leaves the name's own choice in front: kept, though the chip drops the rest.
    pick(batches, show, named(CHIP, CAST), KEEP, lead=True)
    pick(batches, show, CHIP, DROP)
    assert dropped(batches, director) == [3]
    assert dropped(batches, cast) == []
    pick(batches, show, named(CHIP, CAST), TrackChoice(Verdict.PASS), lead=True)
    assert dropped(batches, cast) == [3]


def test_a_show_s_rule_by_name_reaches_its_seasons_and_the_season_overrides_it_for_itself(
    tmp_path: Path, store: ProfileStore, director: MediaItem
) -> None:
    other = episode(tmp_path, 1, DIRECTOR, season=2)
    batches = Batches(store)
    show, season = BatchKey.of(director, whole_show=True), BatchKey.of(director)
    pick(batches, show, named(CHIP, DIRECTOR), DROP, lead=True)
    assert dropped(batches, director) == dropped(batches, other) == [3]
    assert batches.received_choice(season, named(CHIP, DIRECTOR)) == DROP
    # Season 1 keeps that name: its rule hides the show's, so the plan is not left with two rules on one name.
    pick(batches, season, named(CHIP, DIRECTOR), KEEP, lead=True)
    assert dropped(batches, director) == []
    assert dropped(batches, other) == [3]
    own = batches.own_tracks(season).rules
    layered = layered_rules(own, batches.profile(show).for_stage("tracks").rules)
    assert [r.verdict for r in layered] == [Verdict.KEEP]
    # Choosing what the season receives makes it follow the show again; no rule is kept for it.
    pick(batches, season, named(CHIP, DIRECTOR), DROP, lead=True)
    assert batches.own_tracks(season).rules == []
    assert dropped(batches, director) == [3]


def test_a_nearer_chip_choice_decides_before_a_rule_by_name_from_above_but_only_where_it_chose(
    tmp_path: Path, store: ProfileStore, director: MediaItem
) -> None:
    other = episode(tmp_path, 1, DIRECTOR, season=2)
    batches = Batches(store)
    show, season = BatchKey.of(director, whole_show=True), BatchKey.of(director)
    pick(batches, show, named(CHIP, DIRECTOR), DROP, lead=True)
    assert dropped(batches, director) == dropped(batches, other) == [3]
    # Season 1 keeps the chip: its choice is tried first, so the name the show drops is kept there and only there.
    pick(batches, season, CHIP, KEEP)
    assert dropped(batches, director) == []
    assert dropped(batches, other) == [3]
    # A choice of the season that decides nothing about keeping leaves the show's name rule to decide.
    pick(batches, season, CHIP, STAR)
    pick(batches, season, CHIP, TrackChoice(Verdict.PASS, default=True))
    assert dropped(batches, director) == [3]


def test_dropping_a_name_changes_where_the_default_goes_by_the_rules_that_exist(
    tmp_path: Path, store: ProfileStore
) -> None:
    """Flags: the name rule carries none. The chips' stars stay, and the star of the second chip is the fallback in
    the file whose first track the name rule dropped."""
    first = episode(tmp_path, 1, DIRECTOR)
    first = replace(first, file=replace(first.file, tracks=(replace(ENGLISH, name="English (Original)"), TURKISH)))
    second = episode(tmp_path, 2, DIRECTOR)
    second = replace(second, file=replace(second.file, tracks=(ENGLISH, TURKISH)))
    batches = Batches(store)
    show = BatchKey.of(first, whole_show=True)
    english, turkish = TrackSignature.of(ENGLISH), TrackSignature.of(TURKISH)
    pick(batches, show, english, STAR)
    pick(batches, show, turkish, STAR)
    assert defaults(batches, first) == defaults(batches, second) == [1]
    pick(batches, show, named(english, "English (Original)"), DROP, lead=True)
    assert dropped(batches, first) == [1]
    assert defaults(batches, first) == [2]
    assert defaults(batches, second) == [1]
    rule = batches.profile(show).for_stage("tracks").rules[0]
    assert (rule.default, rule.forced) == (FlagShape.LEAVE, FlagShape.LEAVE)


def test_discard_takes_a_season_s_rules_by_name_with_its_other_choices(
    tmp_path: Path, store: ProfileStore, director: MediaItem
) -> None:
    batches = Batches(store)
    show, season = BatchKey.of(director, whole_show=True), BatchKey.of(director)
    pick(batches, show, named(CHIP, DIRECTOR), KEEP, lead=True)
    pick(batches, season, named(CHIP, DIRECTOR), DROP, lead=True)
    pick(batches, season, TrackSignature.of(TURKISH), DROP)
    assert batches.discard_of(season).own == 2
    assert dropped(batches, director) == [2, 3]
    batches.discard(season)
    assert batches.own_tracks(season).rules == []
    assert dropped(batches, director) == []
