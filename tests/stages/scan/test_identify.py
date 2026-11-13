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
        ("lib/Movies/Alien (1979) 1080p.mkv", False, Movie("Alien", 1979)),
        ("lib/Movies/Aliens.1986.BluRay.x264-GROUP.mkv", False, Movie("Aliens", 1986)),
        # One movie per folder: the folder name has the year.
        ("lib/The Matrix (1999)/the.matrix.1080p.mkv", True, Movie("The Matrix", 1999)),
        ("lib/The Matrix (1999)/movie.mkv", True, Movie("The Matrix", 1999)),
        # A year in the file name wins over the folder.
        ("lib/Collection/Heat (1995).mkv", True, Movie("Heat", 1995)),
        # No year anywhere: the file name.
        ("lib/Downloads/Some Movie 1080p.mkv", True, Movie("Some Movie", None)),
        # Many movies in one folder never borrow from the folder.
        ("lib/Movies (2020)/Heat.mkv", False, Movie("Heat", None)),
    ],
)
def test_movies(path: str, alone: bool, expected: Movie) -> None:
    assert identify(Path(path), alone=alone) == expected
