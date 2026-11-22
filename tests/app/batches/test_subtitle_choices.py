"""Subtitle settings by place: the per-item fields (wanted languages, rule sets, engine settings) are laid over what a
place receives item by item, the others whole, and each kind of own value goes with Discard."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import Batches, BatchKey
from showrunner.app.jobs.groups import ChangeGroup, without
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.media import Episode, MediaFile, MediaItem
from showrunner.stages.subtitles import Approval, RuleSetUse, SubtitlesOptions, SyncEngine, Wanted

WANTED, NOT_HERE = Wanted.WANTED, Wanted.NOT_HERE


def episode(number: int) -> MediaItem:
    path = Path(f"Show Name - S01E{number:02}.mkv")
    return MediaItem(Episode("Show Name", 1, number), MediaFile(path, "matroska"))


@pytest.fixture
def batches(tmp_path: Path) -> Batches:
    (tmp_path / "profiles").mkdir()
    return Batches(ProfileStore(tmp_path / "profiles"))


ITEM = episode(1)
SHOW, SEASON, FILE = BatchKey.of(ITEM, whole_show=True), BatchKey.of(ITEM), BatchKey.file(ITEM)


def subtitles(batches: Batches, key: BatchKey) -> SubtitlesOptions:
    return batches.profile(key).for_stage("subtitles")


def edit(batches: Batches, key: BatchKey, **changes: object) -> None:
    batches.set_options(key, "subtitles", replace(subtitles(batches, key), **changes))


def test_a_nearer_place_adds_and_cancels_items_and_still_receives_later_ones(batches: Batches) -> None:
    edit(batches, SHOW, languages={"tr": WANTED}, cleanup={"Lyrics": RuleSetUse.USED})
    # The season adds German, says no to Turkish and pauses the show's set.
    edit(
        batches,
        SEASON,
        languages={"tr": NOT_HERE, "de": WANTED},
        cleanup={"Lyrics": RuleSetUse.PAUSED, "Ads": RuleSetUse.USED},
    )
    assert batches.own(SEASON)["subtitles"] == {
        "languages": {"tr": NOT_HERE, "de": WANTED},
        "cleanup": {"Lyrics": RuleSetUse.PAUSED, "Ads": RuleSetUse.USED},
    }
    # A language the show adds later still reaches the season and its episodes.
    edit(batches, SHOW, languages={"tr": WANTED, "fr": WANTED})
    assert subtitles(batches, FILE).wanted() == ("fr", "de")
    assert subtitles(batches, FILE).rule_sets() == ("Ads",)
    assert batches.item_origin(FILE, "subtitles", "languages", "fr") == SHOW
    assert batches.item_origin(FILE, "subtitles", "languages", "tr") == SEASON
    assert batches.item_origin(FILE, "subtitles", "languages", "it") is None


def test_an_item_set_back_to_what_is_received_follows_the_parent_again(batches: Batches) -> None:
    edit(batches, SHOW, languages={"tr": WANTED})
    edit(batches, SEASON, languages={"tr": NOT_HERE, "de": WANTED})
    edit(batches, SEASON, languages={"tr": WANTED, "de": WANTED})
    assert batches.own(SEASON)["subtitles"] == {"languages": {"de": WANTED}}
    assert batches.item_origin(SEASON, "subtitles", "languages", "tr") == SHOW


def test_whole_fields_override_and_as_it_is_is_a_value(batches: Batches) -> None:
    edit(batches, SHOW, sync=SyncEngine.FFSUBSYNC, approval=Approval.TRANSLATIONS, sync_settings={"alass.x": "1"})
    edit(batches, SEASON, sync=SyncEngine.AS_IT_IS, sync_settings={"alass.y": "2"})
    season = subtitles(batches, FILE)
    assert (season.sync, season.approval) == (SyncEngine.AS_IT_IS, Approval.TRANSLATIONS)
    # Engine settings are per field, so the season still has the show's.
    assert season.sync_settings == {"alass.x": "1", "alass.y": "2"}
    assert batches.field_origin(FILE, "subtitles", "sync") == SEASON


def test_discard_removes_every_own_value_and_a_saved_workspace_keeps_them(batches: Batches, tmp_path: Path) -> None:
    edit(batches, SHOW, languages={"tr": WANTED})
    edit(batches, SEASON, languages={"tr": NOT_HERE, "de": WANTED}, sync=SyncEngine.ALASS)
    loaded = Batches.from_json(ProfileStore(tmp_path / "profiles"), batches.to_json())
    assert loaded.own(SEASON) == batches.own(SEASON)
    batches.discard(SEASON)
    assert subtitles(batches, FILE).wanted() == ("tr",)
    assert subtitles(batches, FILE).sync is SyncEngine.AS_IT_IS


def test_a_kept_place_receives_no_subtitle_work_but_keeps_how_it_is_done(batches: Batches) -> None:
    edit(batches, SHOW, languages={"tr": WANTED}, model="Sample 9B Instruct", sync=SyncEngine.ALASS)
    batches.keep(SEASON)
    kept = subtitles(batches, FILE)
    assert (kept.wanted(), kept.sync, kept.model) == ((), SyncEngine.AS_IT_IS, "Sample 9B Instruct")
    assert batches.item_origin(SEASON, "subtitles", "languages", "tr") == SEASON


def test_leaving_the_group_out_empties_only_the_work() -> None:
    asked = SubtitlesOptions(
        languages={"tr": WANTED},
        cleanup={"Lyrics": RuleSetUse.USED},
        sync=SyncEngine.ALASS,
        sync_settings={"alass.x": "1"},
        model="Sample 9B Instruct",
        approval=Approval.EVERY,
    )
    profile = Profile.defaults("p").with_options("subtitles", asked)
    left = without(profile, ChangeGroup.SUBTITLES)
    assert left.for_stage("subtitles") == SubtitlesOptions(sync_settings={"alass.x": "1"}, model="Sample 9B Instruct")
    # The other groups leave subtitles alone.
    assert without(profile, ChangeGroup.NAMES).for_stage("subtitles") == asked
    assert without(profile, ChangeGroup.TRACKS).for_stage("subtitles") == asked
