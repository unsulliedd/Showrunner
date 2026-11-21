from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.core.media import Episode, Movie
from showrunner.stages.scan.identify import identify


def test_episode_with_everything_in_the_file_name() -> None:
    path = Path("lib/Show Name (1992) S03E04 Snowfall.mkv")
    assert identify(path, alone=False) == Episode("Show Name", 3, 4, 1992, "Snowfall")


def test_scene_name_ends_the_title_at_the_release_words() -> None:
    path = Path("lib/The.Show.S14E04.The.Long.Road.720p.HDTV.x264-GROUP.mkv")
    assert identify(path, alone=False) == Episode("The Show", 14, 4, None, "The Long Road")


def test_show_and_year_come_from_the_folders_when_the_name_lacks_them() -> None:
    path = Path("lib/Some Show (2010)/Season 2/S02E05 - Title Here.mkv")
    assert identify(path, alone=False) == Episode("Some Show", 2, 5, 2010, "Title Here")


def test_show_folder_without_a_season_folder() -> None:
    path = Path("lib/Some Show (2010)/S01E02.mkv")
    assert identify(path, alone=False) == Episode("Some Show", 1, 2, 2010, "")


def test_season_folder_gives_the_season_to_a_name_with_only_a_number() -> None:
    assert identify(Path("lib/Show (2010)/Season 3/04 - Title.mkv"), alone=False) == Episode(
        "Show", 3, 4, 2010, "Title"
    )
    assert identify(Path("lib/Show (2010)/S03/Episode 12.mkv"), alone=False) == Episode("Show", 3, 12, 2010, "")


def test_run_together_code_counts_only_inside_a_season_folder() -> None:
    assert identify(Path("lib/Show/Season 3/Show - 305 - Title.mkv"), alone=False) == Episode(
        "Show", 3, 5, None, "Title"
    )
    # Outside one, "300" is the title of a movie.
    assert identify(Path("lib/Movies/300 (2006).mkv"), alone=False) == Movie("300", 2006)


@pytest.mark.parametrize(
    ("path", "alone", "expected"),
    [
        ("lib/Movies/Example (1979) 1080p.mkv", False, Movie("Example", 1979)),
        ("lib/Movies/Examples.1986.BluRay.x264-GROUP.mkv", False, Movie("Examples", 1986)),
        # One movie per folder: the folder name has the year.
        ("lib/The Example (1999)/the.example.1080p.mkv", True, Movie("The Example", 1999)),
        ("lib/The Example (1999)/movie.mkv", True, Movie("The Example", 1999)),
        # A year in the file name wins over the folder.
        ("lib/Collection/Alpha (1995).mkv", True, Movie("Alpha", 1995)),
        # No year anywhere: the file name.
        ("lib/Downloads/Some Movie 1080p.mkv", True, Movie("Some Movie", None)),
        # Many movies in one folder never borrow from the folder.
        ("lib/Movies (2020)/Alpha.mkv", False, Movie("Alpha", None)),
    ],
)
def test_movies(path: str, alone: bool, expected: Movie) -> None:
    assert identify(Path(path), alone=alone) == expected


@pytest.mark.parametrize(
    ("name", "last", "title"),
    [
        ("Show Name - S01E01-E02 - Episode One.mkv", 2, "Episode One"),
        ("Show.Name.S01E01E02.Episode.One.mkv", 2, "Episode One"),
        ("Show Name s01e01-e02 Episode One.mkv", 2, "Episode One"),
        ("Show Name S01E01-S01E02 Episode One.mkv", 2, "Episode One"),
        ("Show Name S01E01-02 Episode One.mkv", 2, "Episode One"),
        ("Show Name S01E01E02E03 Episode One.mkv", 3, "Episode One"),
        ("Show Name 1x01-1x02 Episode One.mkv", 2, "Episode One"),
        ("Show Name 1x01-02 Episode One.mkv", 2, "Episode One"),
        ("Show Name 1x01x02 Episode One.mkv", 2, "Episode One"),
    ],
)
def test_two_episodes_in_one_file_keep_the_first_as_the_episode_and_the_last_beside_it(
    name: str, last: int, title: str
) -> None:
    assert identify(Path("lib") / name, alone=False) == Episode("Show Name", 1, 1, None, title, last)


@pytest.mark.parametrize(
    "name",
    [
        "Show Name S01E01 - 24 Hours.mkv",  # a spaced dash is no range
        "Show Name S01E01-720p.mkv",
        "Show Name S01E01-1080p.mkv",
        "Show Name 1x01.x264.mkv",
        "Show Name S01E02-E01.mkv",  # a last episode before the first is no range
        "Show Name S01E01-E01.mkv",
    ],
)
def test_a_dash_or_number_after_the_code_is_no_range_unless_it_is_an_episode_after_the_first(name: str) -> None:
    found = identify(Path("lib") / name, alone=False)
    assert isinstance(found, Episode)
    assert found.last_episode is None
