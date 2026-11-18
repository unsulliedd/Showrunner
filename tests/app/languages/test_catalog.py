"""The language lists with and without MKVToolNix (its adapter faked), and the check of a typed tag."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from showrunner.app.languages import TagProblem, catalog, check_tag, load_known_codes, read_languages, use_languages
from showrunner.core.language import Language, add_languages, languages
from showrunner.tools.mkvtoolnix.languages import ListLanguagesError, MkvLanguage
from showrunner.tools.process import ProgramNotFoundError

ROWS = (
    MkvLanguage("German", "ger", "ger", "de"),
    MkvLanguage("Dutch", "dut", "dut", "nl"),
    MkvLanguage("Portuguese", "por", "por", "pt"),
    MkvLanguage("Romance languages", "roa", "roa", ""),
    MkvLanguage("Berber languages", "ber", "ber", ""),
)
MKVMERGE = Path("mkvmerge.exe")


@pytest.fixture(autouse=True)
def no_extra_languages() -> Iterator[None]:
    add_languages({})
    yield
    add_languages({})


def test_without_the_program_the_picker_has_babelfish_and_every_tag_is_checked_by_it_alone() -> None:
    assert load_known_codes(None) is None
    assert any(row.code == "por" for row in languages())
    assert not any(row.code == "roa" for row in languages())
    assert check_tag("pt-BR", None).problem is TagProblem.NONE
    assert check_tag("roa", None).problem is TagProblem.NOT_A_TAG


def test_with_the_program_its_extra_codes_join_the_list_and_its_codes_are_known() -> None:
    known = use_languages(ROWS)
    assert known is not None
    assert {"ger", "de", "roa", "ber", "nl"} <= known
    codes = {row.code for row in languages()}
    assert {"roa", "ber"} <= codes
    assert next(row for row in languages() if row.code == "roa").name == "Romance languages"
    # babelfish's own rows are not doubled by the program's.
    assert sum(row.code == "por" for row in languages()) == 1
    assert Language.parse("roa") == Language("roa")


def test_the_codes_of_a_program_that_is_gone_are_forgotten() -> None:
    use_languages(ROWS)
    assert use_languages(None) is None
    assert not any(row.code == "roa" for row in languages())


@pytest.mark.parametrize("text", ["de", "deu", "ger", "German", "de-CH", "nl", "nld", "dut", "pt-BR", "roa", "es-419"])
def test_a_tag_whose_language_the_program_knows_passes_under_any_of_its_codes(text: str) -> None:
    known = use_languages((*ROWS, MkvLanguage("Spanish", "spa", "spa", "es")))
    assert check_tag(text, known).problem is TagProblem.NONE


def test_a_language_babelfish_knows_but_the_program_does_not_gets_a_warning_not_a_refusal() -> None:
    known = use_languages(ROWS)
    check = check_tag("tur", known)
    assert check.problem is TagProblem.UNKNOWN_TO_MKVTOOLNIX
    assert check.language == Language("tur")
    assert check_tag("tur", None).problem is TagProblem.NONE


@pytest.mark.parametrize("text", ["", "  ", "xx", "pt-XX", "sr-Abcd", "not a tag", "und", "pt-BR-"])
def test_text_that_is_no_tag_is_said_so(text: str) -> None:
    check = check_tag(text, use_languages(ROWS))
    assert (check.language, check.problem) == (None, TagProblem.NOT_A_TAG)


def test_the_program_is_asked_once_through_its_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[Path] = []

    def listing(program: Path, **_: object) -> tuple[MkvLanguage, ...]:
        asked.append(program)
        return ROWS

    monkeypatch.setattr(catalog, "list_languages", listing)
    assert read_languages(MKVMERGE) == ROWS
    assert asked == [MKVMERGE]
    assert read_languages(None) is None
    assert asked == [MKVMERGE]


@pytest.mark.parametrize("error", [ListLanguagesError("no list"), ProgramNotFoundError("gone", ["mkvmerge"])])
def test_a_program_that_gives_no_list_leaves_the_picker_with_babelfish(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def broken(program: Path, **_: object) -> tuple[MkvLanguage, ...]:
        raise error

    monkeypatch.setattr(catalog, "list_languages", broken)
    assert load_known_codes(MKVMERGE) is None
    assert any(row.code == "por" for row in languages())
