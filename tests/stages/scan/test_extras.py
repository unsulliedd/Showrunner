from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from showrunner.core.media import Episode, Extra, Movie
from showrunner.stages.scan import scan

Make = Callable[..., Path]


def identities(root: Path) -> dict[str, object]:
    return {i.file.path.relative_to(root).as_posix(): i.identity for i in scan([root]).items}


def test_an_unnumbered_file_in_a_specials_or_season_zero_folder_is_an_extra(tmp_path: Path, make: Make) -> None:
    make("Show Name (2020)/Season 1/Show Name - S01E01.mkv")
    make("Show Name (2020)/Specials/Behind the Scenes.mkv")
    make("Show Name (2020)/Season 00/Bloopers.mkv")
    found = identities(tmp_path)
    assert found["Show Name (2020)/Specials/Behind the Scenes.mkv"] == Extra("Show Name", "Behind the Scenes", 2020)
    assert found["Show Name (2020)/Season 00/Bloopers.mkv"] == Extra("Show Name", "Bloopers", 2020)


def test_a_special_with_an_episode_number_stays_an_episode(tmp_path: Path, make: Make) -> None:
    make("Show Name (2020)/Specials/Show Name - S00E03 - Holiday.mkv")
    make("Show Name (2020)/Season 00/04 - Recap.mkv")
    assert identities(tmp_path) == {
        "Show Name (2020)/Specials/Show Name - S00E03 - Holiday.mkv": Episode("Show Name", 0, 3, 2020, "Holiday"),
        "Show Name (2020)/Season 00/04 - Recap.mkv": Episode("Show Name", 0, 4, 2020, "Recap"),
    }


@pytest.mark.parametrize(
    "folder",
    ["Extras", "Featurettes", "Deleted Scenes", "behind the scenes", "INTERVIEWS", "Trailers", "Shorts", "Other"],
)
def test_the_usual_extras_folders_of_a_show_hold_extras(tmp_path: Path, make: Make, folder: str) -> None:
    make("Show Name (2020)/Season 1/Show Name - S01E01.mkv")
    make(f"Show Name (2020)/{folder}/Making Of.mkv")
    assert identities(tmp_path)[f"Show Name (2020)/{folder}/Making Of.mkv"] == Extra("Show Name", "Making Of", 2020)


def test_an_extras_folder_inside_a_season_belongs_to_the_show(tmp_path: Path, make: Make) -> None:
    make("Show Name (2020)/Season 1/Show Name - S01E01.mkv")
    make("Show Name (2020)/Season 1/Extras/Making Of.mkv")
    assert identities(tmp_path)["Show Name (2020)/Season 1/Extras/Making Of.mkv"] == Extra(
        "Show Name", "Making Of", 2020
    )


def test_a_show_is_known_by_its_season_folders_alone(tmp_path: Path, make: Make) -> None:
    make("Show Name (2020)/Season 1/readme.txt")
    make("Show Name (2020)/Featurettes/Making Of.mkv")
    assert identities(tmp_path) == {"Show Name (2020)/Featurettes/Making Of.mkv": Extra("Show Name", "Making Of", 2020)}


def test_an_unnumbered_file_directly_in_a_show_folder_is_an_extra_and_a_numbered_one_an_episode(
    tmp_path: Path, make: Make
) -> None:
    make("Show Name (2020)/Show Name - S01E01.mkv")
    make("Show Name (2020)/Show Name - S01E02.mkv")
    make("Show Name (2020)/Interview with the Cast.mkv")
    found = identities(tmp_path)
    assert found["Show Name (2020)/Interview with the Cast.mkv"] == Extra("Show Name", "Interview with the Cast", 2020)
    assert found["Show Name (2020)/Show Name - S01E02.mkv"] == Episode("Show Name", 1, 2, 2020)


def test_the_extras_of_a_dropped_subfolder_are_still_extras(tmp_path: Path, make: Make) -> None:
    make("Show Name (2020)/Season 1/Show Name - S01E01.mkv")
    make("Show Name (2020)/Extras/Making Of.mkv")
    found = scan([tmp_path / "Show Name (2020)" / "Extras"]).items
    assert [i.identity for i in found] == [Extra("Show Name", "Making Of", 2020)]


def test_a_folder_of_movies_stays_movies(tmp_path: Path, make: Make) -> None:
    make("Movies/Example (1979).mkv")
    make("Movies/Examples (1986).mkv")
    make("Movies/Extras/Example Trailer.mkv")
    make("Movies/Other/Something.mkv")
    assert set(identities(tmp_path).values()) == {
        Movie("Example", 1979),
        Movie("Examples", 1986),
        Movie("Example Trailer"),
        Movie("Something"),
    }


def test_the_extras_folder_of_a_movie_stays_movies(tmp_path: Path, make: Make) -> None:
    make("Movie Title (2016)/Movie Title (2016).mkv")
    make("Movie Title (2016)/Featurettes/Making Of.mkv")
    assert all(isinstance(i, Movie) for i in identities(tmp_path).values())


def test_an_unnumbered_file_in_a_numbered_season_is_not_an_extra(tmp_path: Path, make: Make) -> None:
    make("Show Name (2020)/Season 1/Show Name - S01E01.mkv")
    make("Show Name (2020)/Season 1/Pilot.mkv")
    assert identities(tmp_path)["Show Name (2020)/Season 1/Pilot.mkv"] == Movie("Pilot")
