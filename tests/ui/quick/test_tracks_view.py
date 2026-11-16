"""What Overview and Tracks draw, built from the neutral sample season, its choices and its live plan."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.app.batches.batch import BatchKey
from showrunner.app.batches.choices import TrackChoice, add_paired, choose
from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.stages import pipeline
from showrunner.app.library.library import Library
from showrunner.app.profiles.store import ProfileStore
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaItem
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.mux.options import Original
from showrunner.stages.tracks import (
    FlagShape,
    FlagTest,
    KindTest,
    SourceTest,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
)
from showrunner.tools.probe import Programs
from showrunner.ui.quick.tracks import BatchView, columns, rule_parts

from .conftest import named_after_episode

# Mux and Metadata plan with a made-up program path; nothing runs it.
STAGES = pipeline(Programs(mkvmerge=Path("mkvmerge")), Path("mkvpropedit"))
ENGLISH, TURKISH, COMMENTARY, STEREO, SDH, ENGLISH_SUBS, FORCED, SRT = range(8)


@pytest.fixture
def season(library: Library) -> list[MediaItem]:
    return [i for i in library.items if BatchKey.of(i) == BatchKey.of(library.items[0])]


def view(items: list[MediaItem], options: TracksOptions, *, planned: bool = True) -> BatchView:
    profile = ProfileStore().load("Default").value.with_options("tracks", options)
    files = preview(items, profile, STAGES, stamped=False).files if planned else ()
    return BatchView.build(items, options, files)


def chosen(items: list[MediaItem]) -> TracksOptions:
    """The approved board's choices: commentary and SDH dropped, Turkish audio default else English, the Turkish
    forced subtitles forced, the paired file added and default."""
    cols = columns(items)
    options = TracksOptions()
    options = choose(options, cols[COMMENTARY].signature, TrackChoice(Verdict.DROP))
    options = choose(options, cols[TURKISH].signature, TrackChoice(Verdict.KEEP, default=True))
    options = choose(options, cols[ENGLISH].signature, TrackChoice(Verdict.KEEP, default=True))
    options = choose(options, cols[SDH].signature, TrackChoice(Verdict.DROP))
    options = choose(options, cols[FORCED].signature, TrackChoice(Verdict.KEEP, forced=True))
    paired = cols[SRT].paired
    assert paired is not None
    options = add_paired(options, paired, True)
    return choose(options, cols[SRT].signature, TrackChoice(Verdict.KEEP, default=True))


def test_columns_are_audio_then_subtitles_then_paired_files(season: list[MediaItem]) -> None:
    cols = columns(season)
    names = [h["name"] for h in view(season, TracksOptions(), planned=False).headers()]
    assert [(c.signature.kind.value, name) for c, name in zip(cols, names, strict=True)] == [
        ("audio", "English"),
        ("audio", "Turkish"),
        ("audio", "Commentary"),
        ("audio", "Stereo"),
        ("subtitle", "SDH"),
        ("subtitle", "English"),
        ("subtitle", "Forced"),
        ("subtitle", ""),
    ]
    assert cols[SRT].paired is not None
    assert all(c.paired is None for c in cols[:SRT])


def test_headers_show_the_choices_and_the_files_that_lack_a_track(season: list[MediaItem]) -> None:
    headers = view(season, chosen(season)).headers()
    assert [h["state"] for h in headers] == ["kept", "kept", "dropped", "kept", "dropped", "kept", "kept", "added"]
    assert [h["count"] for h in headers] == [
        "",
        "missing in 1 file",
        "",
        "missing in 9 files",
        "",
        "",
        "missing in 1 file",
        "",
    ]
    assert (headers[TURKISH]["default"], headers[FORCED]["forced"], headers[SRT]["default"]) == (True, True, True)
    assert (headers[SRT]["title"], headers[TURKISH]["code"]) == (".srt file", "TUR")


def test_a_chip_names_the_files_that_lack_its_track(season: list[MediaItem]) -> None:
    built = view(season, TracksOptions(), planned=False)
    assert built.missing(ENGLISH) == ""  # every file has it: no count, nothing to name
    assert built.headers()[ENGLISH]["count"] == ""
    assert built.missing(TURKISH) == "Missing in 07"  # Episode Seven has no Turkish audio
    assert built.missing(99) == ""
    assert [i.identity.episode for i in built.lacking(STEREO)] == [1, 2, 3, 4, 5, 6, 7, 8, 10]  # type: ignore[union-attr]


def test_a_paired_file_beside_some_files_has_a_list_of_the_files_without_it(season: list[MediaItem]) -> None:
    built = view(season, TracksOptions(), planned=False)
    assert (built.headers()[SRT]["count"], built.headers()[SRT]["names"]) == ("", False)
    bare = [replace(season[3], subtitles=()), *season[:3], *season[4:]]
    header = view(bare, TracksOptions(), planned=False).headers()[SRT]
    assert (header["count"], header["names"]) == ("missing in 1 file", True)


def test_a_file_that_could_not_be_read_is_neither_counted_as_having_nor_as_lacking_a_track(
    season: list[MediaItem],
) -> None:
    third = season[2]
    items = [*season[:2], replace(third, file=replace(third.file, tracks=())), *season[3:]]
    unmarked = BatchView.build(items, TracksOptions(), ())
    marked = BatchView.build(items, TracksOptions(), (), failures={str(third.file.path): "Not a Matroska file"})
    assert len(marked.cols) == len(unmarked.cols)
    for index in range(len(marked.cols)):
        # Without the mark an empty file lacks every embedded track (the paired file beside it is still there).
        assert (items[2] in unmarked.lacking(index)) is (index < SRT)
        assert items[2] not in marked.lacking(index)
    # Only Episode Seven lacks the Turkish audio; the unread Episode Three says nothing about it.
    assert marked.headers()[TURKISH]["count"] == "missing in 1 file"
    assert marked.missing(TURKISH) == "Missing in 07"
    assert unmarked.headers()[TURKISH]["count"] == "missing in 2 files"
    assert all(h["count"] == "" for h in marked.headers()[:1])  # a track every readable file has shows no count


def test_a_paired_file_not_added_is_offered_and_takes_no_flag(season: list[MediaItem]) -> None:
    header = view(season, TracksOptions()).headers()[SRT]
    assert (header["state"], header["flags"], header["button"]) == ("paired", False, "Add")


def test_before_the_plan_arrives_the_files_show_their_tracks_as_they_are(season: list[MediaItem]) -> None:
    unplanned = view(season, chosen(season), planned=False)
    # The chip shows the choice at once; the files, and the count of files that keep the track, wait for the plan.
    assert unplanned.headers()[COMMENTARY]["state"] == "dropped"
    assert all(row["cells"][COMMENTARY]["state"] == "kept" for row in unplanned.rows())
    assert unplanned.headers()[COMMENTARY]["count"] == ""
    assert unplanned.rows()[0]["changes"] == 0


def test_rows_carry_pills_changes_and_the_fallback_warning(season: list[MediaItem]) -> None:
    rows = view(season, chosen(season)).rows()
    third, seventh = rows[2], rows[6]
    assert [(p["code"], p["state"], p["default"]) for p in third["audio"]] == [
        ("ENG", "kept", False),
        ("TUR", "kept", True),
        ("ENG", "dropped", False),
    ]
    assert [(p["code"], p["added"]) for p in third["subtitles"]][-1] == ("TUR", True)
    # A new file, the default audio and the default subtitles moving.
    assert (third["changes"], third["changes_text"], third["warning"]) == (3, "3 changes", "")
    assert seventh["warning"] == "No Turkish audio: English audio becomes the default"
    assert seventh["cells"][ENGLISH]["fallback"] is True
    assert third["cells"][ENGLISH]["fallback"] is False
    assert seventh["cells"][TURKISH]["state"] == "missing"


def test_rules_that_leave_no_audio_say_so_on_the_row(season: list[MediaItem]) -> None:
    drop_audio = TracksOptions(rules=[TrackRule(match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.DROP)])
    built = view(season, drop_audio)
    assert built.rows()[0]["warning"] == "Tracks stay as they are: the choices would leave no audio"
    # The refused plan is not carried out, so the tracks show as they are.
    assert built.headers()[ENGLISH]["state"] == "kept"


def test_rules_read_as_sentences_with_their_fallbacks(season: list[MediaItem]) -> None:
    rules = view(season, chosen(season)).rules()
    words = [" ".join(str(p["text"]) for p in rule["parts"]) for rule in rules]
    assert words[:3] == [
        "Drop audio in ENG Dolby Digital 2.0 flagged commentary",
        "Keep audio in TUR Dolby Digital Plus 5.1 · default",
        "Keep audio in ENG Dolby Digital Plus 5.1 · default if none above",
    ]
    assert words[-1] == "Keep subtitles in TUR SubRip from a file beside the video · default"
    assert [r["fits"] for r in rules[:3]] == ["fits 10 files", "fits 9 files", "fits 10 files"]
    assert all(r["from_choice"] and r["source"] == "from the matrix" for r in rules)


def test_a_hand_written_rule_reads_from_its_match() -> None:
    rule = TrackRule(
        match=TrackMatch(kind=KindTest.SUBTITLE, languages=["tr"], forced=FlagTest.UNSET, min_channels=0),
        verdict=Verdict.KEEP,
        default=FlagShape.FIRST,
    )
    parts = rule_parts(rule, None, [])
    assert " ".join(str(p["text"]) for p in parts) == "Keep subtitles in TR not forced · default"
    assert [p["text"] for p in parts if p["code"]] == ["TR"]
    words = {
        source: " ".join(str(p["text"]) for p in rule_parts(TrackRule(match=TrackMatch(source=source)), None, []))
        for source in SourceTest
    }
    assert words == {
        SourceTest.ANY: "Set tracks",
        SourceTest.EMBEDDED: "Set tracks inside the file",
        SourceTest.PAIRED: "Set tracks from a file beside the video",
    }


def test_movie_cards_hold_the_choice_and_the_name(library: Library) -> None:
    movie = library.items[-3]
    cols = columns([movie])
    options = choose(TracksOptions(), cols[2].signature, TrackChoice(Verdict.DROP))
    groups = view([movie], options).card_groups(movie)
    audio, subtitles = groups
    assert audio["count"] == "3 → 2"
    assert [c["state"] for c in audio["cards"]] == ["kept", "kept", "dropped"]
    assert audio["cards"][0]["is_default"]
    assert not audio["cards"][0]["default"]
    assert (audio["cards"][0]["name"], audio["cards"][0]["was"]) == ("English", "as is")
    assert subtitles["cards"][-1]["state"] == "paired"


def test_the_inspector_groups_what_changes(season: list[MediaItem]) -> None:
    file = view(season, chosen(season)).inspector(season[2], Original.RECYCLE)
    assert file["name"] == "Episode Three"
    assert file["facts"].startswith("S01E03 · Show Name (2020) · ")
    assert [c["text"] for c in file["changes"]] == [
        "New file with 6 of 7 tracks",
        "Default: Turkish audio, Turkish subtitles",
    ]
    assert file["changes"][0]["detail"].endswith("Recycle Bin")
    assert file["count"] == 3
    states = [(t["code"], t["state"]) for t in file["tracks"]]
    assert states[3] == ("ENG", "dropped")
    assert states[-1] == ("TUR", "added")
    assert file["track_count"] == "7 → 6"


def test_tracks_named_per_episode_are_one_column_with_each_file_s_name_in_its_list(season: list[MediaItem]) -> None:
    named = [named_after_episode(i) for i in season]
    named[1] = replace(named[1], file=replace(named[1].file, tracks=season[1].file.tracks))  # its own names again
    built = view(named, TracksOptions(), planned=False)
    headers = built.headers()
    assert len(headers) == len(columns(season))
    # A chip names what the track is when the files name it apart, or the name every file gives it.
    assert [h["name"] for h in headers[:3]] == ["", "", "Commentary"]
    assert headers[STEREO]["name"] == "Show Name - 1x09 - Episode Nine (Stereo)"  # one file has it
    assert [h["name"] for h in headers[4:7]] == ["SDH", "", "Forced"]
    assert all(h["names"] for h in headers[:SRT])
    assert not headers[SRT]["names"]
    turkish = built.names(TURKISH)
    assert turkish[:2] == ["01 · Show Name - 1x01 - Episode One (Turkish)", "02 · Turkish"]
    assert len(turkish) == 9  # Episode Seven has no Turkish audio
    assert built.names(SRT) == []
    unnamed = [
        replace(i, file=replace(i.file, tracks=tuple(replace(t, name="") for t in i.file.tracks))) for i in named
    ]
    assert view(unnamed, TracksOptions(), planned=False).names(ENGLISH)[0] == "01 · no name"


def test_a_whole_show_lists_files_by_season_and_episode(library: Library) -> None:
    show = [i for i in library.items if isinstance(i.identity, Episode) and i.identity.show == "Show Name"]
    names = view(show, TracksOptions(), planned=False).names(ENGLISH)
    assert (names[0], names[-1]) == ("S01E01 · English", "S02E08 · English")


def test_an_embedded_twin_of_the_paired_file_named_per_episode_is_one_more_column(season: list[MediaItem]) -> None:
    paired = columns(season)[SRT].signature
    twin = Track(
        30, TrackKind.SUBTITLE, paired.codec, Language.parse(paired.language), "Turkish", subtitle=SubtitleProperties()
    )
    items = [named_after_episode(replace(i, file=replace(i.file, tracks=(*i.file.tracks, twin)))) for i in season]
    cols = columns(items)
    assert len(cols) == len(columns(season)) + 1
    inside = next(c for c in cols if c.signature == replace(paired, paired=False))
    assert inside.paired is None
    assert inside.signature.name is None
    assert cols[-1].signature == paired  # the paired file's column, as without the twin
    assert len(view(items, TracksOptions(), planned=False).names(cols.index(inside))) == len(season)


def test_two_alike_tracks_in_one_file_are_two_columns_named_apart(season: list[MediaItem]) -> None:
    first = season[0]
    extra = replace(first.file.tracks[1], id=20, name="Director")
    items = [replace(first, file=replace(first.file, tracks=(*first.file.tracks, extra))), *season[1:]]
    built = view(items, TracksOptions())
    names = [h["name"] for h in built.headers() if h["kind"] == "audio"]
    assert names == ["English", "Turkish", "Commentary", "Director", "Stereo"]
    director = names.index("Director")
    options = choose(TracksOptions(), built.cols[director].signature, TrackChoice(Verdict.DROP))
    dropped = view(items, options)
    assert [h["state"] for h in dropped.headers()][: len(names)] == ["kept", "kept", "kept", "dropped", "kept"]
    words = " ".join(str(p["text"]) for p in dropped.rules()[0]["parts"])
    assert words == "Drop audio in ENG Dolby Digital Plus 5.1 named Director"
