"""Deciding whether a video is a movie or an episode, from its name and its folders."""

from __future__ import annotations

import re
from pathlib import Path

from showrunner.core.media import Episode, Movie
from showrunner.stages.scan.names import (
    find_code,
    find_year,
    leading_title,
    parse_movie_name,
    parse_show_folder,
    season_of_folder,
    spaced,
)

# `Episode 4`, `E04` or `04 - Title`: an episode number without a season, which a season folder supplies.
_NUMBER_ONLY = re.compile(r"(?:episode|ep|e)?[ ._-]*(\d{1,3})(?![A-Za-z0-9])", re.IGNORECASE)


def identify(path: Path, *, alone: bool) -> Movie | Episode:
    """What the video is. `alone` says it is the only video in its folder, the one-movie-per-folder layout."""
    text = spaced(path.stem)
    season_folder = season_of_folder(path.parent.name)
    # A bare "305" is only read as an episode where a season folder says this is a show.
    code = find_code(text, run_together=season_folder is not None)
    if code:
        season, number, start, end, last = code.season, code.episode, code.start, code.end, code.last
    elif season_folder is not None and (found := _NUMBER_ONLY.match(text)):
        season, number, start, end, last = season_folder, int(found[1]), 0, found.end(), None
    else:
        return _movie(path, alone)

    show, year = _show(text[:start], path.parent.parent if season_folder is not None else path.parent)
    return Episode(show, season, number, year, leading_title(text[end:]), last)


def _show(before_code: str, show_folder: Path) -> tuple[str, int | None]:
    """The show and its year from the file name, with the show folder filling in what the name lacks."""
    year = find_year(before_code)
    show = leading_title(before_code[: year[1]] if year else before_code)
    folder_show, folder_year = parse_show_folder(show_folder.name)
    return show or folder_show, year[0] if year else folder_year


def _movie(path: Path, alone: bool) -> Movie:
    title, year = parse_movie_name(path.stem)
    if alone and year is None:
        folder_title, folder_year = parse_movie_name(path.parent.name)
        # A folder with a year is the better source; so is any folder when the name has no title.
        if folder_year is not None or not title:
            title, year = folder_title or title, folder_year
    return Movie(title or path.stem, year)
