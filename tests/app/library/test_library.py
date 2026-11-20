from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from showrunner.app.library.library import Library, LibraryLoad, Mark
from showrunner.core.media import Extra, SubtitleFile


def path_of(library: Library, name: str) -> Path:
    return next(i.file.path for i in library.items if name in i.file.path.name)


def alternative_of(library: Library, video: Path) -> SubtitleFile:
    return next(a for a in library.alternatives if a.video == video).subtitles[0]


def test_marks_come_from_alternatives_and_failures(sample_library: Library) -> None:
    marks = {i.file.path.name: sample_library.mark(i.file.path) for i in sample_library.items}
    assert marks == {
        "Alpha S01E01.mkv": Mark.NONE,
        "Alpha S01E02.mkv": Mark.UNSURE,
        "Alpha S02E01.mkv": Mark.NONE,
        "Beta S01E01.mkv": Mark.FAILED,
        "Movie Title (2016).mkv": Mark.NONE,
    }


def test_counts_cover_the_library_or_a_subset(sample_library: Library) -> None:
    counts = sample_library.counts()
    assert (counts.videos, counts.episodes, counts.movies) == (5, 4, 1)
    assert (counts.unsure, counts.failed, counts.unpaired, counts.needs_look) == (1, 1, 1, 2)
    season = sample_library.counts([path_of(sample_library, "S01E01"), path_of(sample_library, "S01E02")])
    assert (season.videos, season.unsure, season.failed, season.unpaired) == (2, 1, 0, 1)


def test_unpaired_files_are_found_by_the_folder_of_a_video(sample_library: Library) -> None:
    assert len(sample_library.unpaired_near([path_of(sample_library, "S01E01")])) == 1
    assert sample_library.unpaired_near([path_of(sample_library, "S02E01")]) == ()


def test_pair_here_moves_an_unpaired_file_to_a_video(sample_library: Library) -> None:
    extra = sample_library.unpaired[0]
    video = path_of(sample_library, "S02E01")
    paired = sample_library.pair(extra, video)
    assert paired.unpaired == ()
    assert paired.item(video).subtitles == (extra,)
    assert sample_library.unpaired == (extra,)  # the library it was made from is unchanged


def test_unpair_lists_the_file_as_unpaired(sample_library: Library) -> None:
    video = path_of(sample_library, "S01E01")
    subtitle = sample_library.item(video).subtitles[0]
    result = sample_library.unpair(subtitle)
    assert result.item(video).subtitles == ()
    assert subtitle in result.unpaired


def test_pair_instead_swaps_the_file_and_settles_the_doubt(sample_library: Library) -> None:
    video = path_of(sample_library, "S01E02")
    attached = sample_library.item(video).subtitles[0]
    alternative = alternative_of(sample_library, video)
    result = sample_library.pair_instead(video, alternative)
    assert result.item(video).subtitles == (alternative,)
    assert attached in result.unpaired
    assert result.alternatives == ()
    assert result.mark(video) is Mark.NONE


def test_pair_instead_keeps_a_file_of_another_language(sample_library: Library) -> None:
    video = path_of(sample_library, "S01E02")
    english = SubtitleFile(Path("lib/Alpha/S01/Alpha S01E02.en.srt"), sample_library.unpaired[0].language)
    library = sample_library.pair(english, video)
    alternative = alternative_of(library, video)
    result = library.pair_instead(video, alternative)
    assert english in result.item(video).subtitles
    assert alternative in result.item(video).subtitles


def test_pair_instead_ignores_a_file_that_is_not_an_alternative(sample_library: Library) -> None:
    assert sample_library.pair_instead(path_of(sample_library, "S01E01"), sample_library.unpaired[0]) == sample_library


def test_merge_adds_new_videos_and_does_not_list_a_known_subtitle_twice(sample_library: Library) -> None:
    known = sample_library.unpaired[0]
    attached = sample_library.item(path_of(sample_library, "S01E01")).subtitles[0]
    load = LibraryLoad(items=(), unpaired=(known, attached), roots=(Path("lib"), Path("other")))
    merged = sample_library.merge(load)
    assert merged.unpaired == (known,)
    assert merged.roots == (Path("lib"), Path("other"))


def test_files_read_again_after_apply_take_their_place_and_lose_the_subtitles_moved_away(
    sample_library: Library,
) -> None:
    first = sample_library.item(path_of(sample_library, "S01E01"))
    renamed = replace(first.file, path=first.file.path.with_name("Alpha S01E01 new.mkv"), title="New")
    gone = first.subtitles[0].path
    library = sample_library.with_files({first.file.path: renamed}, gone=[gone])
    moved = library.item(renamed.path)
    assert moved is not None
    assert moved.identity == first.identity
    assert (moved.file.title, moved.subtitles) == ("New", ())
    assert library.item(first.file.path) is None
    assert [i.file.path for i in library.items][1:] == [i.file.path for i in sample_library.items][1:]


def test_extras_are_counted_apart_from_episodes_and_movies(sample_library: Library) -> None:
    extra = replace(sample_library.items[0], identity=Extra("Alpha", "Making Of", 2020))
    extra = replace(extra, file=replace(extra.file, path=Path("lib/Alpha/Extras/Making Of.mkv")))
    stranger = replace(extra, identity=Extra("Gamma", "Trailer"), file=replace(extra.file, path=Path("lib/G/T.mkv")))
    library = replace(sample_library, items=(*sample_library.items, extra, stranger))
    counts = library.counts()
    assert (counts.videos, counts.episodes, counts.movies, counts.extras) == (7, 4, 1, 2)
    assert library.counts([extra.file.path]).extras == 1


def test_without_takes_videos_out_with_their_doubts_and_failures_and_keeps_the_rest(sample_library: Library) -> None:
    doubt, failed = path_of(sample_library, "S01E02"), path_of(sample_library, "Beta")
    library = sample_library.without([doubt, failed])
    assert [i.file.path.name for i in library.items] == [
        "Alpha S01E01.mkv",
        "Alpha S02E01.mkv",
        "Movie Title (2016).mkv",
    ]
    assert (library.alternatives, library.failures) == ((), ())
    assert library.unpaired == sample_library.unpaired
    assert library.roots == sample_library.roots
    assert sample_library.without([]) == sample_library


def test_folders_of_names_the_opened_folders_that_hold_the_videos(sample_library: Library) -> None:
    alpha = path_of(sample_library, "S01E01")
    library = replace(sample_library, roots=(Path("lib/Alpha"), Path("lib/Beta")))
    assert library.folders_of([alpha]) == (Path("lib/Alpha"),)
    assert library.folders_of([alpha, path_of(library, "Beta")]) == (Path("lib/Alpha"), Path("lib/Beta"))
    assert library.folders_of([path_of(library, "Movie")]) == ()
    assert replace(sample_library, roots=()).folders_of([alpha]) == ()  # opened one by one: no folder


def test_closed_removes_the_folder_with_everything_listed_from_it(sample_library: Library) -> None:
    library = replace(sample_library, roots=(Path("lib/Alpha"), Path("lib/Beta")))
    closed = library.closed([Path("lib/Alpha")])
    assert [i.file.path.name for i in closed.items] == ["Beta S01E01.mkv", "Movie Title (2016).mkv"]
    assert closed.roots == (Path("lib/Beta"),)
    assert closed.alternatives == ()  # the doubt was about an Alpha episode
    assert [f.path.name for f in closed.failures] == ["Beta S01E01.mkv"]
    assert closed.unpaired == ()
