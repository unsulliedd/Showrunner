"""What Review draws, built from the neutral sample season with the approved board's choices and a title template."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from showrunner.app.batches.batch import BatchKey, Media
from showrunner.app.batches.choices import TrackChoice, choose
from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.stages import pipeline
from showrunner.app.library.library import Library
from showrunner.app.profiles.profile import Profile
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.media import Episode, MediaItem
from showrunner.stages.mux.options import MuxOptions, Original
from showrunner.stages.subtitles import Wanted
from showrunner.stages.tracks import TrackMatch, TrackRule, TracksOptions, Verdict
from showrunner.tools.probe import Programs
from showrunner.ui.quick.review import ReviewInput, parts, review, totals
from showrunner.ui.quick.tracks import columns

from .test_tracks_view import SDH, STAGES, TURKISH, chosen


@pytest.fixture
def season(library: Library) -> list[MediaItem]:
    return [i for i in library.items if BatchKey.of(i) == BatchKey.of(library.items[0])]


def profile_for(items: list[MediaItem], **mux: Any) -> Profile:
    profile = ProfileStore().load("Default").value.with_options("tracks", chosen(items))
    naming = replace(profile.for_stage("naming"), title_template="{show} - S{season:00}E{episode:00}")
    return profile.with_options("naming", naming).with_options("mux", MuxOptions(**mux))


def given_for(items: list[MediaItem], profile: Profile, stages: Any = STAGES, **given: Any) -> ReviewInput:
    out = frozenset(given.pop("groups_out", ()))
    full = preview(items, profile, stages, stamped=False).files
    run = preview(items, profile, stages, left_out=out, stamped=False).files if out else full
    return ReviewInput(
        items=items,
        media=Media.EPISODES,
        tracks=profile.for_stage("tracks"),
        mux=profile.for_stage("mux"),
        run=run,
        full=full,
        groups_out=out,
        blocks=blocked_stages(profile),
        **given,
    )


def built(items: list[MediaItem], profile: Profile, stages: Any = STAGES, **given: Any) -> dict[str, Any]:
    return review(given_for(items, profile, stages, **given))


def lines(card: dict[str, Any]) -> list[tuple[str, int]]:
    return [(line["label"], line["count"]) for line in card["lines"]]


def test_the_changes_are_grouped_by_kind_and_add_up(season: list[MediaItem]) -> None:
    shown = built(season, profile_for(season))
    tracks, names = shown["groups"]
    assert (tracks["title"], tracks["in_run"]) == ("Tracks and new files", True)
    assert lines(tracks) == [("New file", 10), ("Default and forced flags", 19)]
    assert lines(names) == [("Titles", 10)]
    assert (shown["count"], shown["files"]) == (39, 10)
    assert shown["title"] == "39 changes in 10 files"
    assert shown["apply_text"] == "Apply 2 of 2 kinds to 10 files"
    assert [g["label"] for g in shown["groups"]] == ["Tracks and new files · 10 files", "Names and flags · 10 files"]
    assert tracks["original_text"] == "Originals: Recycle Bin"
    assert shown["stays"] == ["Subtitles", "File names", "Chapters", "Attachments", "Artwork"]


def test_an_unticked_kind_says_what_it_would_do_and_counts_nothing(season: list[MediaItem]) -> None:
    shown = built(season, profile_for(season), groups_out={ChangeGroup.NAMES})
    _tracks, names = shown["groups"]
    assert names["in_run"] is False
    assert lines(names) == [("Titles", 10)]  # drawn struck: what it would do
    assert names["note"] == "Unticked. The templates stay with this batch and are planned again next time."
    assert names["label"] == "Names and flags · 10 files"  # what it would change, ticked or not
    assert shown["count"] == 29
    assert shown["apply_text"] == "Apply 1 of 2 kinds to 10 files"
    first = shown["rows"][0]
    assert [m["key"] for m in first["marks"]] == ["tracks", "names"]
    assert [(m["on"], m["out"]) for m in first["marks"]] == [(True, False), (False, True)]
    title = next(d for d in first["detail"] if d["label"] == "Title")
    assert (title["after"], title["out"]) == ("Show Name - S01E01", True)


def test_an_unticked_file_stays_listed_and_leaves_the_counts(season: list[MediaItem]) -> None:
    profile = profile_for(season)
    ninth = season[8].file.path
    shown = built(season, profile, files_out={ninth})
    assert (shown["count"], shown["files"]) == (35, 9)
    assert shown["apply_text"] == "Apply 2 of 2 kinds to 9 files"
    assert [(f["key"], f["count"]) for f in shown["filters"]] == [("all", 10), ("look", 1)]
    row = next(r for r in shown["rows"] if r["path"] == str(ninth))
    assert row["state"] == "out"
    assert row["summary"].startswith("4 changes")  # still planned
    looks = built(season, profile, filter="look")["rows"]
    assert [r["title"] for r in looks] == ["Episode Seven"]  # no Turkish audio: English takes the default
    assert looks[0]["warning"] == "No Turkish audio: English audio becomes the default"


def test_the_totals_are_the_reviews_count_without_its_cards(season: list[MediaItem]) -> None:
    profile = profile_for(season)
    for given in (
        given_for(season, profile),
        given_for(season, profile, groups_out={ChangeGroup.NAMES}),
        given_for(season, profile, files_out={season[8].file.path}),
    ):
        shown = review(given)
        assert totals(given) == (shown["count"], shown["files"])


def test_a_file_card_shows_its_tracks_defaults_file_and_title_before_and_after(season: list[MediaItem]) -> None:
    first = built(season, profile_for(season, original=Original.KEEP))["rows"][0]
    assert first["summary"] == "4 changes · new file, 2 flags, title"
    detail = {d["label"]: d for d in first["detail"]}
    assert list(detail) == ["Video", "Audio", "Subtitles", "Default", "File", "Title", "Flags", ""]
    assert [(p["code"], p["state"]) for p in detail["Video"]["after"]] == [("UND", "kept")]
    audio = detail["Audio"]
    assert [p["code"] for p in audio["before"]] == ["ENG", "TUR", "ENG"]
    assert [(p["code"], p["state"], p["default"]) for p in audio["after"]] == [
        ("ENG", "kept", False),
        ("TUR", "kept", True),
        ("ENG", "dropped", False),
    ]
    assert [p["added"] for p in detail["Subtitles"]["after"]] == [False, False, False, True]
    assert detail["Default"]["before"] == "English audio · no subtitles"
    assert detail["Default"]["after"] == "Turkish audio · Turkish subtitles"
    assert detail["File"]["after"] == "New file, checked, then the original moves to .originals"


def test_problems_and_missing_programs_are_worded_in_place(season: list[MediaItem]) -> None:
    profile = profile_for(season)
    broken = replace(profile.for_stage("tracks"), rules=[TrackRule(match=TrackMatch(languages=["xx1"]))])
    profile = profile.with_options("tracks", broken).with_options("mux", MuxOptions(suffix="a|b"))
    tracks, names = built(season, profile, mkvtoolnix_missing=True)["groups"]
    assert tracks["problems"] == [
        "New files and flags need MKVToolNix, which is not installed.",
        "Rule 1 has a problem, so no track choice is planned until it is fixed.",
        "The name suffix holds a character a file name cannot have, so no new file is planned.",
    ]
    assert tracks["program"] is True
    assert names["problems"] == ["Names need MKVToolNix, which is not installed."]


def test_nothing_set_up_says_so(season: list[MediaItem]) -> None:
    profile = ProfileStore().load("Default").value.with_options("tracks", TracksOptions())
    shown = built(season, profile)
    assert [g["note"] for g in shown["groups"]] == [
        "No track choices, so the tracks stay as they are.",
        "No templates, so titles and names stay as they are.",
    ]
    assert (shown["count"], shown["title"], shown["apply_text"]) == (0, "Nothing to apply", "Nothing to apply")


def test_parts_add_up_to_the_counts(season: list[MediaItem]) -> None:
    file = preview(season[:1], profile_for(season), STAGES, stamped=False).files[0]
    assert parts(file) == {
        "new_file": 1,
        "order": 0,
        "flags": 2,
        "titles": 1,
        "names": 0,
        "languages": 0,
        "implied": 0,
        "subtitles": 0,
        "subtitle_file": 0,
    }
    assert parts(None) == dict.fromkeys(parts(file), 0)
    assert Path(file.item.file.path).name == "Show.Name.S01E01.mkv"


def test_changes_no_program_can_write_are_not_offered_to_apply(season: list[MediaItem]) -> None:
    shown = built(season, profile_for(season), pipeline(Programs(), None), mkvtoolnix_missing=True)
    assert (shown["count"], shown["apply_text"]) == (0, "Nothing to apply")
    assert {r["state"] for r in shown["rows"]} == {"look"}
    assert shown["rows"][0]["warning"] == "Needs MKVToolNix to write the new file"
    assert shown["groups"][0]["lines"] == []


def test_an_excluded_file_is_not_an_unticked_one(season: list[MediaItem]) -> None:
    profile = profile_for(season)
    shown = built(season, profile, excluded={season[2].file.path}, files_out={season[3].file.path})
    states = {r["title"]: r["state"] for r in shown["rows"]}
    assert (states["Episode Three"], states["Episode Four"]) == ("excluded", "out")
    assert shown["apply_text"] == "Apply 2 of 2 kinds to 8 files"
    assert [g["label"] for g in shown["groups"]] == ["Tracks and new files · 8 files", "Names and flags · 8 files"]


def with_implied_flags(items: list[MediaItem], *, remux: bool) -> Profile:
    """Turkish audio default and the commentary kept, whose name implies a flag it lacks. With `remux` the SDH
    subtitles are dropped, which needs a new file; without it the headers are edited in place."""
    cols = columns(items)
    options = choose(TracksOptions(), cols[TURKISH].signature, TrackChoice(Verdict.KEEP, default=True))
    if remux:
        options = choose(options, cols[SDH].signature, TrackChoice(Verdict.DROP))
    profile = profile_for(items).with_options("tracks", options)
    return profile.with_options("metadata", replace(profile.for_stage("metadata"), write_implied_flags=True))


def edits(row: dict[str, Any]) -> list[tuple[str, str, bool]]:
    return [(d["label"], d["text"], d["out"]) for d in row["detail"] if d["text"]]


NAMED = [
    ("Flags", "Default flag removed from “English”", False),
    ("", "Default flag set on “Turkish”", False),
    ("", "Commentary flag set on “Commentary”", False),
]


@pytest.mark.parametrize(("remux", "summary"), [(False, "3 changes"), (True, "4 changes")])
def test_every_flag_change_is_named_by_track_and_flag(season: list[MediaItem], remux: bool, summary: str) -> None:
    # In place Metadata writes the flags the rules move; in a new file the track plan does. Each is named once.
    shown = built(season, with_implied_flags(season, remux=remux))
    row = shown["rows"][0]
    assert row["summary"].startswith(summary)
    assert row["summary"].endswith("1 implied flag")
    assert edits(row) == NAMED
    assert shown["groups"][1]["lines"][-1] == {"label": "Flags the names imply", "count": 10}


def test_flag_lines_of_an_unticked_kind_are_marked_out(season: list[MediaItem]) -> None:
    profile = with_implied_flags(season, remux=False)
    names = edits(built(season, profile, groups_out={ChangeGroup.NAMES})["rows"][0])
    assert [out for _label, _text, out in names] == [False, False, True]  # the rules' flags are the Tracks kind's
    tracks = edits(built(season, profile, groups_out={ChangeGroup.TRACKS})["rows"][0])
    assert [out for _label, _text, out in tracks] == [True, True, False]


def test_over_more_seasons_a_divider_names_each_season_above_its_first_file(library: Library) -> None:
    first = library.items[0].identity
    show = [i for i in library.items if isinstance(i.identity, Episode) and i.identity.show == first.show]
    rows = built(show, profile_for(show))["rows"]
    marked = [(n, r["season"]) for n, r in enumerate(rows) if r["season"]]
    assert [text for _, text in marked] == ["Season 1", "Season 2"]
    assert [n for n, _ in marked] == [0, 10]
    # One season alone needs no divider.
    season = [i for i in show if BatchKey.of(i) == BatchKey.of(show[0])]
    assert all(r["season"] == "" for r in built(season, profile_for(season))["rows"])


def test_a_names_problem_stays_on_the_names_card(season: list[MediaItem]) -> None:
    profile = profile_for(season)
    naming = replace(profile.for_stage("naming"), title_template="{no_such_token}")
    subtitles = replace(profile.for_stage("subtitles"), languages={"de": Wanted.WANTED})
    profile = profile.with_options("naming", naming).with_options("subtitles", subtitles)
    groups = {g["key"]: g for g in built(season, profile)["groups"]}
    assert groups["names"]["problems"] != []
    # No engine translates in this version, so the subtitles card says that, and only that.
    assert groups["subtitles"]["problems"] == [
        "Translate is not available in this version yet, so 10 subtitles are left out. The rest of each file goes on"
        " without them."
    ]
