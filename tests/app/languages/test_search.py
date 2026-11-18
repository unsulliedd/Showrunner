"""The picker's list: what a query finds and in which order."""

from __future__ import annotations

import pytest

from showrunner.app.languages import LanguageIndex
from showrunner.core.language import languages


@pytest.fixture(scope="module")
def index() -> LanguageIndex:
    return LanguageIndex.of(languages())


def codes(rows: list) -> list[str]:
    return [row.code for row in rows]


def test_with_no_query_the_batch_comes_first_then_the_languages_with_a_two_letter_code_then_the_rest(
    index: LanguageIndex,
) -> None:
    found = index.search("", {"cmn", "tur"})
    assert len(found) == len(languages()) > 7800
    assert codes(found)[:2] == ["cmn", "tur"]  # the batch's, by name
    common = [row.common for row in found[2:]]
    assert common == sorted(common, reverse=True)  # every common one before the first that is not
    assert sum(common) > 100
    # Inside a group the languages are by name.
    first_common = found[2:][: sum(common)]
    assert [r.name.casefold() for r in first_common] == sorted(r.name.casefold() for r in first_common)


@pytest.mark.parametrize("query", ["port", "PORT", "pt", "por", "Portuguese", "portu gu"])
def test_a_name_or_a_code_finds_the_language_first(index: LanguageIndex, query: str) -> None:
    found = index.search(query)
    assert codes(found)[0] == "por"


def test_an_exact_code_comes_before_names_that_merely_contain_it(index: LanguageIndex) -> None:
    found = codes(index.search("pt"))
    assert found[0] == "por"
    assert len(found) > 3  # names holding "pt" follow, such as Egyptian Arabic


def test_every_word_of_the_query_must_fit(index: LanguageIndex) -> None:
    found = index.search("norwegian bok")
    assert codes(found) == ["nob"]
    assert index.search("zzzzzz") == []


def test_the_batch_s_languages_stay_first_inside_a_search(index: LanguageIndex) -> None:
    plain = codes(index.search("ar"))
    batch = codes(index.search("ar", {"ara"}))
    assert batch[0] == "ara"
    assert sorted(plain) == sorted(batch)


def test_filtering_the_whole_list_is_quick(index: LanguageIndex) -> None:
    import time

    start = time.perf_counter()
    for query in ("a", "po", "chi", "e", "ng"):
        index.search(query, {"eng", "tur"})
    assert time.perf_counter() - start < 2.0
