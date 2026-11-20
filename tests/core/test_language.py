import dataclasses
from collections.abc import Iterator

import pytest

from showrunner.core.language import (
    Language,
    add_languages,
    languages,
    region_name,
    regions,
    scripts,
)


@pytest.fixture(autouse=True)
def no_extra_languages() -> Iterator[None]:
    """The codes MKVToolNix adds are shared state: each test starts and ends without them."""
    add_languages({})
    yield
    add_languages({})


@pytest.mark.parametrize("text", ["tr", "tur", "Turkish", "turkish", " TR "])
def test_parse_turkish_forms_are_equal(text: str) -> None:
    assert Language.parse(text) == Language("tur")


def test_parse_iso_639_2_both_forms() -> None:
    assert Language.parse("ger") == Language.parse("deu") == Language("deu")


def test_parse_region_and_script() -> None:
    brazilian = Language.parse("pt-BR")
    assert brazilian == Language("por", "BR")
    assert brazilian != Language("por")
    assert Language.parse("zh-Hant") == Language("zho", script="Hant")


@pytest.mark.parametrize("text", ["und", "", "  ", "xx", "nonsense", "Klingonish"])
def test_parse_unknown_gives_none(text: str) -> None:
    assert Language.parse(text) is None


def test_exposed_forms() -> None:
    turkish = Language.parse("tur")
    assert turkish is not None
    assert (turkish.ietf, turkish.alpha3, turkish.name) == ("tr", "tur", "Turkish")
    brazilian = Language("por", "BR")
    assert (brazilian.ietf, brazilian.name) == ("pt-BR", "Portuguese")


def test_hash_follows_equality() -> None:
    assert len({Language.parse("tr"), Language.parse("tur"), Language("tur")}) == 1


def test_invalid_code_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a valid language"):
        Language("qqq")


def test_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Language("tur").alpha3 = "eng"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pt-BR", Language("por", "BR")),
        ("PT-br", Language("por", "BR")),
        ("por-BR", Language("por", "BR")),
        ("es-419", Language("spa", "419")),
        ("sr-Latn-RS", Language("srp", "RS", "Latn")),
        ("sr-latn", Language("srp", script="Latn")),
        ("zh-Hant", Language("zho", script="Hant")),
        ("de-CH-1996", Language("deu", "CH", rest="1996")),
        ("en-US-x-foo", Language("eng", "US", rest="x-foo")),
        ("ca-valencia", Language("cat", rest="valencia")),
        ("Serbo-Croatian", Language("hbs")),
    ],
)
def test_a_tag_is_read_whole(text: str, expected: Language) -> None:
    assert Language.parse(text) == expected


@pytest.mark.parametrize(
    "text", ["pt-XX", "pt-Abcd", "xx-BR", "zh-yue", "pt-", "pt--BR", "en-US-toolongsubtag", "und-BR", "es-4", "en-x"]
)
def test_a_tag_with_a_part_that_is_not_one_is_no_language(text: str) -> None:
    assert Language.parse(text) is None


def test_a_tag_is_written_in_its_shortest_form() -> None:
    cases = {
        "por-BR": "pt-BR",
        "sr-Latn-RS": "sr-Latn-RS",
        "es-419": "es-419",
        "de-CH-1996": "de-CH-1996",
        "cmn": "cmn",
        "ger": "de",
    }
    for text, tag in cases.items():
        language = Language.parse(text)
        assert language is not None
        assert language.ietf == tag
        assert Language.parse(tag) == language


def test_the_name_with_the_region_and_script() -> None:
    assert Language("por", "BR").display == "Portuguese (Brazil)"
    assert Language("spa", "419").display == "Spanish (Latin America and the Caribbean)"
    assert Language("srp", "RS", "Latn").display == "Serbian (Latin, Serbia)"
    assert Language("tur").display == "Turkish"
    assert Language("por", "BR").name == "Portuguese"
    assert region_name("BA") == "Bosnia and Herzegovina"


def test_every_code_of_a_language() -> None:
    assert Language("deu").codes == ("deu", "ger", "de")
    assert Language("cmn").codes == ("cmn",)


def test_a_region_and_a_script_must_exist() -> None:
    with pytest.raises(ValueError, match="not a valid region"):
        Language("por", "XX")
    with pytest.raises(ValueError, match="not a valid script"):
        Language("zho", script="Abcd")


def test_what_an_older_file_stored_still_builds_a_language() -> None:
    # The read cache stores a language as its fields; files written before the tag had a rest have three.
    assert Language(**{"alpha3": "por", "region": "BR", "script": None}) == Language("por", "BR")
    assert dataclasses.asdict(Language("por", "BR")) == {"alpha3": "por", "region": "BR", "script": None, "rest": ""}


def test_codes_babelfish_lacks_are_languages_once_a_program_adds_them() -> None:
    assert Language.parse("roa") is None
    add_languages({"roa": "Romance languages", "por": "ignored: babelfish has it"})
    roa = Language.parse("roa")
    assert roa == Language("roa")
    assert (roa.name, roa.ietf, roa.codes) == ("Romance languages", "roa", ("roa",))
    assert Language.parse("roa-BR") == Language("roa", "BR")
    assert Language("por").name == "Portuguese"
    # Only a code finds them: a word of a file name never becomes one of these.
    assert Language.parse("Romance languages") is None
    add_languages({})
    assert Language.parse("roa") is None
    # A language built while the codes were there stays usable when they go.
    add_languages({"roa": "Romance languages"})
    kept = Language("roa")
    add_languages({})
    assert (kept.name, kept.ietf, kept.display) == ("roa", "roa", "roa")


def test_the_lists_of_the_picker() -> None:
    names = [row.name for row in languages()]
    assert len(names) > 7800
    assert names == sorted(names, key=str.casefold)
    portuguese = next(row for row in languages() if row.code == "por")
    assert (portuguese.common, "pt" in portuguese.codes) == (True, True)
    assert not next(row for row in languages() if row.code == "cmn").common
    assert len(regions()) >= 249
    assert ("419", "Latin America and the Caribbean") in regions()
    assert ("BR", "Brazil") in regions()
    assert len(scripts()) >= 169
    assert ("Latn", "Latin") in scripts()
    add_languages({"roa": "Romance languages"})
    assert any(row.code == "roa" for row in languages())
