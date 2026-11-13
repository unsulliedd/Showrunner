from __future__ import annotations

import pytest

from showrunner.core.language import Language
from showrunner.stages.scan.names import (
    episode_code,
    find_code,
    match_tokens,
    parse_movie_name,
    parse_show_folder,
    parse_subtitle_name,
    season_of_folder,
)


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("Show (1992) S03E04 Title", (3, 4)),
        ("Show.S14E04.720p.HDTV.x264-GROUP (Tag)", (14, 4)),
        ("show_s01e02_title", (1, 2)),
        ("Show S1 E2", (1, 2)),
        ("Show - 9x05 - Title", (9, 5)),
        ("Show - 305 - Title", (3, 5)),
        ("Show.1204.Title", (12, 4)),
        # Years, resolutions and codec numbers are not codes.
        ("The Matrix (1999) 1080p", None),
        ("Movie 1992 720p x264", None),
        ("Movie 2160p HDR H 264", None),
        ("Show 1920x1080", None),
        ("Title", None),
    ],
)
def test_episode_code_reads_all_spellings(name: str, code: tuple[int, int] | None) -> None:
    assert episode_code(name) == code


def test_run_together_code_is_off_unless_asked_for() -> None:
    assert find_code("Show - 305 - Title") is None
    assert find_code("Show - 305 - Title", run_together=True) is not None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("The Matrix (1999) 1080p BluRay", ("The Matrix", 1999)),
        ("The.Matrix.1999.1080p.BluRay.x264-GROUP", ("The Matrix", 1999)),
        ("2001 A Space Odyssey (1968)", ("2001 A Space Odyssey", 1968)),
        ("Movie Title [2010]", ("Movie Title", 2010)),
        ("1917.2019.1080p.BluRay", ("1917", 2019)),
        ("No Year 1080p WEB-DL", ("No Year", None)),
        ("Spider-Man (2002)", ("Spider-Man", 2002)),
    ],
)
def test_movie_name(name: str, expected: tuple[str, int | None]) -> None:
    assert parse_movie_name(name) == expected


def test_show_folder_keeps_name_and_year_of_a_release_folder() -> None:
    name = "Show Name (1992-) S01-S23 (1080p BDRip x265 10bit TrueHD + AC3 5.1 - group)"
    assert parse_show_folder(name) == ("Show Name", 1992)


@pytest.mark.parametrize(
    ("name", "season"),
    [
        ("Season 2", 2),
        ("Season 10 (1080p)", 10),
        ("S03", 3),
        ("Series 4", 4),
        ("Specials", 0),
        ("Show Name", None),
        ("S01-S23 Pack", None),
    ],
)
def test_season_of_folder(name: str, season: int | None) -> None:
    assert season_of_folder(name) == season


def test_subtitle_name_with_a_language_tag() -> None:
    parsed = parse_subtitle_name("Show - 305 - Title.tr.srt")
    assert (parsed.base, parsed.language, parsed.forced, parsed.sdh) == (
        "Show - 305 - Title",
        Language("tur"),
        False,
        False,
    )


@pytest.mark.parametrize(
    ("file_name", "language", "forced", "sdh"),
    [
        ("Movie.2010.eng.forced.srt", Language("eng"), True, False),
        ("Movie.Turkish.sdh.srt", Language("tur"), False, True),
        ("Movie.hi.tur.srt", Language("tur"), False, True),
        ("Movie.cc.en.srt", Language("eng"), False, True),
        ("Movie.pt-BR.srt", Language("por", "BR"), False, False),
        ("Movie.forced.srt", None, True, False),
        ("Movie.default.tr.srt", Language("tur"), False, False),
    ],
)
def test_subtitle_name_flags_and_languages(file_name: str, language: Language | None, forced: bool, sdh: bool) -> None:
    parsed = parse_subtitle_name(file_name)
    assert (parsed.language, parsed.forced, parsed.sdh) == (language, forced, sdh)


@pytest.mark.parametrize(
    "file_name",
    [
        "Show.Name.S14E04.720p.HDTV.x264-GROUP (Tag).srt",
        "Show - 9x05 - The Long Road.srt",
        "Show.S01E01.Man.srt",  # "man" is a language code, but of no common language
    ],
)
def test_subtitle_name_without_a_language(file_name: str) -> None:
    parsed = parse_subtitle_name(file_name)
    assert parsed.language is None
    assert parsed.base == file_name.removesuffix(".srt")


def test_match_tokens_drop_release_words_codes_and_brackets() -> None:
    assert match_tokens("Show.Name.S14E04.720p.HDTV.x264-GROUP (Tag)") == ["show", "name", "group"]
    assert match_tokens("Show Name - 305 - Mr. Baker's Holiday") == ["show", "name", "mr", "bakers", "holiday"]
