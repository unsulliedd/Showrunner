import dataclasses

import pytest

from showrunner.core.language import Language


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
