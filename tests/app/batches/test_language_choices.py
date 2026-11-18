"""The language a chip gives its tracks: a field of the chip's own rule, so it follows the places (the show's reaches
its seasons and episodes, a nearer place's choice replaces it, a choice of nothing hides it) and goes with Discard."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import Batches, BatchKey
from showrunner.app.batches.choices import NO_CHOICE, TrackChoice, TrackSignature, choice_of, choose
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.core.naming import NamingOptions
from showrunner.core.track import AudioProperties, Track, TrackKind
from showrunner.stages.metadata import MetadataOptions, MetadataPlan, plan_metadata
from showrunner.stages.tracks import TracksOptions, Verdict
from showrunner.tools.mkvtoolnix.propedit import Property

ENGLISH = Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), "English", audio=AudioProperties(6))
TURKISH = Track(2, TrackKind.AUDIO, "A_AC3", Language("tur"), "Turkish", audio=AudioProperties(6))
CHIP = TrackSignature.of(ENGLISH)
LATIN_AMERICAN = TrackChoice(language="es-419")
BRAZILIAN = TrackChoice(language="pt-BR")


def episode(tmp_path: Path, number: int, season: int = 1) -> MediaItem:
    path = tmp_path / f"Show Name - S{season:02}E{number:02}.mkv"
    path.write_bytes(b"matroska")
    return MediaItem(Episode("Show Name", season, number), MediaFile(path, "matroska", tracks=(ENGLISH, TURKISH)))


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    (tmp_path / "profiles").mkdir()
    return ProfileStore(tmp_path / "profiles")


def given(batches: Batches, item: MediaItem) -> list[str]:
    """The tag the open batch's rules give the English track of the file."""
    profile = batches.profile(BatchKey.file(item))
    result = plan_metadata(item, MetadataOptions(), NamingOptions(), profile.for_stage("tracks"))
    assert isinstance(result, MetadataPlan)
    return [str(c.new) for c in result.changes if c.prop is Property.LANGUAGE]


def pick(batches: Batches, key: BatchKey, choice: TrackChoice) -> None:
    batches.set_options(key, "tracks", batches.with_choice(key, CHIP, choice))


def test_a_language_is_one_more_part_of_the_chip_s_choice() -> None:
    options = choose(TracksOptions(), CHIP, TrackChoice(Verdict.KEEP, default=True, language="es-419"))
    (rule,) = options.rules
    assert (rule.from_choice, rule.verdict, rule.language) == (True, Verdict.KEEP, "es-419")
    assert choice_of(options, CHIP) == TrackChoice(Verdict.KEEP, True, False, "es-419")
    # A language alone is a choice too: it decides nothing about keeping.
    only = choose(TracksOptions(), CHIP, LATIN_AMERICAN)
    assert choice_of(only, CHIP) == LATIN_AMERICAN
    assert only.rules[0].verdict is Verdict.PASS
    # Taking it back with nothing else chosen removes the rule.
    assert choose(only, CHIP, NO_CHOICE).rules == []


def test_a_drop_keeps_the_language_so_undoing_it_gives_it_back() -> None:
    options = choose(TracksOptions(), CHIP, TrackChoice(Verdict.DROP, True, False, "pt-BR"))
    assert choice_of(options, CHIP) == TrackChoice(Verdict.DROP, False, False, "pt-BR")


def test_a_show_s_language_reaches_its_seasons_and_episodes(store: ProfileStore, tmp_path: Path) -> None:
    one, two = episode(tmp_path, 1), episode(tmp_path, 2, season=2)
    batches = Batches(store)
    show = BatchKey.of(one, whole_show=True)
    pick(batches, show, LATIN_AMERICAN)
    assert given(batches, one) == given(batches, two) == ["es-419"]
    assert batches.received_choice(BatchKey.file(one), CHIP) == LATIN_AMERICAN


def test_a_nearer_place_chooses_another_language_or_nothing_for_itself(store: ProfileStore, tmp_path: Path) -> None:
    one, two = episode(tmp_path, 1), episode(tmp_path, 2)
    batches = Batches(store)
    pick(batches, BatchKey.of(one, whole_show=True), LATIN_AMERICAN)
    pick(batches, BatchKey.file(one), BRAZILIAN)
    assert given(batches, one) == ["pt-BR"]
    assert given(batches, two) == ["es-419"]
    # "As it is" is a value too: the episode keeps its language though the show gives one.
    pick(batches, BatchKey.file(one), NO_CHOICE)
    assert given(batches, one) == []
    assert given(batches, two) == ["es-419"]
    # The same choice as the show's is no choice of its own: the episode follows the show again.
    pick(batches, BatchKey.file(one), LATIN_AMERICAN)
    assert batches.own_tracks(BatchKey.file(one)).rules == []
    assert given(batches, one) == ["es-419"]


def test_discard_takes_a_place_s_language_and_it_follows_its_parent_again(store: ProfileStore, tmp_path: Path) -> None:
    one = episode(tmp_path, 1)
    batches = Batches(store)
    pick(batches, BatchKey.of(one, whole_show=True), LATIN_AMERICAN)
    pick(batches, BatchKey.file(one), BRAZILIAN)
    assert given(batches, one) == ["pt-BR"]
    batches.discard(BatchKey.file(one))
    assert given(batches, one) == ["es-419"]


def test_a_name_rule_and_the_chip_s_language_work_beside_each_other(store: ProfileStore, tmp_path: Path) -> None:
    item = episode(tmp_path, 1)
    batches = Batches(store)
    key = BatchKey.of(item, whole_show=True)
    pick(batches, key, replace(LATIN_AMERICAN, verdict=Verdict.KEEP))
    named_signature = replace(CHIP, name="English")
    batches.set_options(key, "tracks", batches.with_choice(key, named_signature, TrackChoice(Verdict.DROP), lead=True))
    rules = batches.profile(BatchKey.file(item)).for_stage("tracks").rules
    assert [(r.verdict, r.language) for r in rules] == [(Verdict.DROP, ""), (Verdict.KEEP, "es-419")]
    # The name's rule drops the track, so the language of the chip has nothing to give it.
    assert given(batches, item) == []
