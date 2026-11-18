"""Deciding whether a video is a movie or an episode, from its name and its folders."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from showrunner.core.media import Episode, Extra, Movie
from showrunner.stages.scan.extensions import EXTRAS_FOLDER_NAMES, VIDEO_EXTENSIONS
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


def holds_show(folder: Path) -> bool:
    """Whether the folder is known to be a show: it holds a season folder or a video with an episode code. A folder
    that cannot be read holds none."""
    try:
        for entry in folder.iterdir():
            if entry.suffix.lower() in VIDEO_EXTENSIONS:
                if find_code(spaced(entry.stem)):
                    return True
            elif season_of_folder(entry.name) is not None and entry.is_dir():
                return True
    except OSError:
        pass
    return False


def identify(path: Path, *, alone: bool, shows: Callable[[Path], bool] = holds_show) -> Movie | Episode | Extra:
    """What the video is. `alone` says it is the only video in its folder, the one-movie-per-folder layout. `shows`
    says whether a folder is a show; the scan gives one that remembers its answers."""
    text = spaced(path.stem)
    season_folder = season_of_folder(path.parent.name)
    # A bare "305" is only read as an episode where a season folder says this is a show.
    code = find_code(text, run_together=season_folder is not None)
    if code:
        season, number, start, end, last = code.season, code.episode, code.start, code.end, code.last
    elif season_folder is not None and (found := _NUMBER_ONLY.match(text)):
        season, number, start, end, last = season_folder, int(found[1]), 0, found.end(), None
    elif extra := _extra(path, season_folder, shows):
        return extra
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


def _extra(path: Path, season_folder: int | None, shows: Callable[[Path], bool]) -> Extra | None:
    """The video as an extra of the show it lies in, when it has no episode number and lies in a season-zero or
    Specials folder, in an extras folder, or directly in a show's folder. An extras folder or a show's own folder
    counts only where the show is known, so the extras folder of a movie and a folder of movies stay movies."""
    folder = path.parent
    if season_folder == 0:
        show_folder = folder.parent
    elif season_folder is not None:
        return None
    elif folder.name.casefold() in EXTRAS_FOLDER_NAMES:
        show_folder = folder.parent.parent if season_of_folder(folder.parent.name) is not None else folder.parent
        if not shows(show_folder):
            return None
    elif shows(folder):
        show_folder = folder
    else:
        return None
    show, year = parse_show_folder(show_folder.name)
    title = parse_movie_name(path.stem)[0] or path.stem
    return Extra(show or show_folder.name, title, year)


def _movie(path: Path, alone: bool) -> Movie:
    title, year = parse_movie_name(path.stem)
    if alone and year is None:
        folder_title, folder_year = parse_movie_name(path.parent.name)
        # A folder with a year is the better source; so is any folder when the name has no title.
        if folder_year is not None or not title:
            title, year = folder_title or title, folder_year
    return Movie(title or path.stem, year)
