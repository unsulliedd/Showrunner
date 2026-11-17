"""What a file or folder name says: episode codes, years, titles and release words."""

from __future__ import annotations

import re
from dataclasses import dataclass

from showrunner.core.language import Language

# Words of release names that are neither show nor title.
_RELEASE_WORDS = frozenset(
    {
        "4k",
        "uhd",
        "hdr",
        "hdr10",
        "hdtv",
        "web",
        "webrip",
        "webdl",
        "dl",
        "bdrip",
        "brrip",
        "bluray",
        "remux",
        "dvdrip",
        "hevc",
        "avc",
        "aac",
        "ac3",
        "eac3",
        "dts",
        "truehd",
        "atmos",
        "ddp5",
        "repack",
        "proper",
        "internal",
        "extended",
        "complete",
        "multi",
        "amzn",
        "nf",
        "dsnp",
        "hmax",
    }
)
_RELEASE_PATTERN = re.compile(r"\d{3,4}[pi]|\d+bit|x26[45]|h26[45]")

_BRACKETED = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_YEAR = r"(?:19|20)\d{2}"
_PAREN_YEAR = re.compile(rf"[(\[]\s*({_YEAR})\s*(?:-\s*(?:{_YEAR})?\s*)?[)\]]")
_BARE_YEAR = re.compile(rf"(?<![A-Za-z0-9])({_YEAR})(?![A-Za-z0-9])")
_SEASON_RANGE_WORD = re.compile(r"s\d{1,2}(?:-s?\d{1,2})?", re.IGNORECASE)

_SEASON_EPISODE = re.compile(r"(?<![A-Za-z0-9])s(\d{1,2})[ ._-]?e(\d{1,3})(?!\d)", re.IGNORECASE)
# `1x01x02` is a range, so an `x` and a number may follow the code.
_CROSS = re.compile(r"(?<![A-Za-z0-9])(\d{1,2})x(\d{2,3})(?:(?![A-Za-z0-9])|(?=x\d{2}(?![A-Za-z0-9])))", re.IGNORECASE)
# What may follow the code of the first episode of a file that holds several: `E02`, `-E02`, `-S01E02`, and `-02` with
# the dash tight against the code, so "S01E01 - 24 Hours" and "S01E01-720p" are no ranges.
_MORE_SEASON_EPISODE = re.compile(
    r"(?:[ ._-]?(?:s\d{1,2}[ ._-]?)?e|-)(\d{1,3})(?:(?![A-Za-z0-9])|(?=e\d))", re.IGNORECASE
)
_MORE_CROSS = re.compile(r"(?:x|-(?:\d{1,2}x)?)(\d{2,3})(?![A-Za-z0-9])", re.IGNORECASE)
# "305" for season 3, episode 5; only as a word of its own, so "1080p" and "x264" never match.
_RUN_TOGETHER = re.compile(r"(?<![^ ._-])(\d{1,2})(\d{2})(?![^ ._-])")

_SEASON_FOLDER = re.compile(
    # A range such as `S01-S23` names a pack of seasons, not one.
    r"(?:(?:season|series|staffel|saison|temporada|sezon)[ ._-]*(\d{1,2})|s(\d{1,2}))(?![A-Za-z0-9])(?!-s?\d)",
    re.IGNORECASE,
)
_SPECIALS_FOLDER = re.compile(r"specials?", re.IGNORECASE)

_SUBTITLE_FLAGS = {"forced": "forced", "sdh": "sdh", "hi": "sdh", "cc": "sdh"}
_IGNORED_SUBTITLE_WORDS = frozenset({"default", "full"})


@dataclass(frozen=True, slots=True)
class EpisodeCode:
    season: int
    episode: int
    start: int
    end: int  # after the last episode of a range
    last: int | None = None  # the last episode of a range such as `S01E01-E02`; None for one episode


def spaced(name: str) -> str:
    """Word separators as spaces, keeping the length so positions stay valid. The dot of "Mr. Baker" stays."""
    return re.sub(r"(?<=\w)\.(?=\w)", " ", name.replace("_", " "))


def is_release_word(word: str) -> bool:
    # Only the part before a dash counts, so "x264-GROUP" is a release word and "Spider-Man" is not.
    head = word.casefold().strip(".,;:-").split("-")[0]
    return head in _RELEASE_WORDS or _RELEASE_PATTERN.fullmatch(head) is not None


def _with_range(text: str, found: re.Match[str], more: re.Pattern[str]) -> EpisodeCode:
    """The code `found`, extended over the episodes that follow it, each one after the last."""
    first = last = int(found[2])
    end = found.end()
    while (tail := more.match(text, end)) and int(tail[1]) > last:
        last, end = int(tail[1]), tail.end()
    return EpisodeCode(int(found[1]), first, found.start(), end, last if last > first else None)


def find_code(text: str, *, run_together: bool = False) -> EpisodeCode | None:
    """The first `S03E01`, `3x01` or (with `run_together`) `301` in the text, with its range such as `S03E01-E02`."""
    for pattern, more in ((_SEASON_EPISODE, _MORE_SEASON_EPISODE), (_CROSS, _MORE_CROSS)):
        if found := pattern.search(text):
            return _with_range(text, found, more)
    if run_together:
        for found in _RUN_TOGETHER.finditer(text):
            # Years and the numbers of video codecs look like codes.
            if not (1900 <= int(found[1] + found[2]) <= 2099 or found[1] + found[2] in ("264", "265")):
                return EpisodeCode(int(found[1]), int(found[2]), found.start(), found.end())
    return None


def find_year(text: str) -> tuple[int, int] | None:
    """A year and where it starts: `(1992)`, `[1992-]` or a bare year that follows some words."""
    if found := _PAREN_YEAR.search(text):
        return int(found[1]), found.start()
    for found in reversed(list(_BARE_YEAR.finditer(text))):
        if text[: found.start()].strip(" .-"):
            return int(found[1]), found.start()
    return None


def leading_title(text: str, *, stop_at_year: bool = False) -> str:
    """The words up to the first bracket group or release word, without the separators around them."""
    words: list[str] = []
    for word in text.split():
        if word[0] in "([{" or is_release_word(word):
            break
        if stop_at_year and words and _BARE_YEAR.fullmatch(word):
            break
        if stop_at_year and words and _SEASON_RANGE_WORD.fullmatch(word):
            break
        words.append(word)
    return " ".join(words).strip(" -._,")


def parse_movie_name(name: str) -> tuple[str, int | None]:
    """Title and year of `The Matrix (1999) 1080p` or `The.Matrix.1999.1080p.BluRay-GROUP`."""
    text = spaced(name)
    found = find_year(text)
    if found:
        return leading_title(text[: found[1]]), found[0]
    return leading_title(text), None


def parse_show_folder(name: str) -> tuple[str, int | None]:
    """Show name and year of a folder such as `Show Name (Year) - S00-S99 (1080p Bluray)`."""
    text = spaced(name)
    found = find_year(text)
    return leading_title(text, stop_at_year=True), found[0] if found else None


def season_of_folder(name: str) -> int | None:
    """The season a folder named `Season 2`, `S03` or `Specials` holds."""
    name = name.strip()
    if _SPECIALS_FOLDER.fullmatch(name):
        return 0
    if found := _SEASON_FOLDER.match(name):
        return int(found[1] or found[2])
    return None


def match_tokens(name: str) -> list[str]:
    """The lower-case words of a name that can tell two names apart, without the episode code."""
    text = _BRACKETED.sub(" ", spaced(name))
    if code := find_code(text, run_together=True):
        text = f"{text[: code.start]} {text[code.end :]}"
    unquoted = re.sub(r"['’`]", "", text)  # noqa: RUF001
    words = re.findall(r"[^\W_]+", unquoted.casefold())
    return [w for w in words if not is_release_word(w) and not w.isdigit()]


def episode_code(name: str) -> tuple[int, int] | None:
    """Season and episode of a name; the three common spellings count the same."""
    code = find_code(spaced(name), run_together=True)
    return (code.season, code.episode) if code else None


@dataclass(frozen=True, slots=True)
class SubtitleName:
    base: str  # the name without the language and flag words
    language: Language | None
    forced: bool
    sdh: bool


def _language_of(word: str) -> Language | None:
    language = Language.parse(word) or Language.parse(word.capitalize())
    # Three-letter codes of languages without a two-letter code ("man", "war") are far more often a word of the title.
    if language is None or (len(word) == 3 and len(language.ietf) == 3):
        return None
    return language


def parse_subtitle_name(file_name: str) -> SubtitleName:
    """Language and flags of `Name.tr.srt`, `Name.eng.forced.srt` or `Name.Turkish.sdh.srt`."""
    parts = file_name.rsplit(".", 1)[0].split(".")
    language: Language | None = None
    flags: set[str] = set()
    end = len(parts)
    # The first part is the name itself, never a tag.
    while end > 1:
        word = parts[end - 1].strip().casefold()
        if word in _SUBTITLE_FLAGS:
            flags.add(_SUBTITLE_FLAGS[word])
        elif word in _IGNORED_SUBTITLE_WORDS:
            pass
        elif language is None and (found := _language_of(word)):
            language = found
        else:
            break
        end -= 1
    return SubtitleName(".".join(parts[:end]), language, "forced" in flags, "sdh" in flags)
