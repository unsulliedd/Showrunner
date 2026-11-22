"""Rule sets as cleanit's YAML, and the folder of the user's sets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.core.language import Language
from showrunner.tools.cleanit import (
    PAUSES,
    Example,
    Match,
    RuleDef,
    RuleKind,
    RuleSet,
    RulesFileError,
    builtin_sets,
    dump_pauses,
    dump_set,
    file_name,
    load_book,
    parse_file,
    set_name_of,
    signature,
    valid_name,
)

RULES = (
    RuleDef(
        "no-ads",
        ("sub.example", "other.example"),
        RuleKind.TEXT,
        Match.CONTAINS,
        None,
        ("tr", "en-US"),
        flags=("ignorecase",),
        examples=(Example("Get it at sub.example", None),),
    ),
    RuleDef("dashes", (r"\s-\s",), replacement=" 2013 ", priority=20, paused=True),
    RuleDef("words", ("[[:upper:]]{3,}",), match=Match.EXACT, replacement=""),
)


def test_an_own_set_survives_being_written_and_read() -> None:
    written = dump_set(RuleSet("mine", RULES, aliases={"[:x:]": "xyz"}))
    parsed = parse_file(written)
    assert parsed.rules == RULES
    assert parsed.aliases == {"[:x:]": "xyz"}
    # The rules are tagged with the set, so cleanit's own command line finds them by it.
    assert "tags:\n    - mine" in written


def test_text_that_is_not_ascii_is_kept_as_it_is() -> None:
    rule = RuleDef("türkçe", ("0131015f0131k",), replacement="ğ")
    assert parse_file(dump_set(RuleSet("tr", (rule,)))).rules == (rule,)


@pytest.mark.parametrize(
    "text",
    [
        "a: [",
        "- just\n- a list",
        "rules:\n  r:\n    patterns: x\n    type: fancy",
        "rules:\n  r:\n    nope: 1\n    patterns: x",
    ],
)
def test_a_file_cleanit_would_not_read_is_refused(text: str) -> None:
    with pytest.raises(RulesFileError):
        parse_file(text)


def test_a_file_may_only_pause_a_rule_it_does_not_define() -> None:
    parsed = parse_file(dump_pauses(frozenset({"drop-brackets[no-sdh]", "a"})))
    assert (parsed.rules, parsed.paused) == ((), frozenset({"drop-brackets[no-sdh]", "a"}))


def test_the_name_of_a_file_is_the_name_of_its_set() -> None:
    assert file_name("my-words") == "cleanit-my-words.yml"
    assert set_name_of("cleanit-my-words.yml") == "my-words"
    assert [set_name_of(n) for n in ("cleanit-.yml", "other.yml", "cleanit-a b.yml", "cleanit-a.yaml")] == [None] * 4
    assert (valid_name("my_set-2"), valid_name("a b"), valid_name("no-sdh"), valid_name(PAUSES)) == (
        "",
        "characters",
        "taken",
        "taken",
    )


def test_the_book_holds_the_users_sets_after_the_built_in_ones(tmp_path: Path) -> None:
    (tmp_path / file_name("mine")).write_text(dump_set(RuleSet("mine", RULES)), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a rule file")
    book = load_book(tmp_path)
    assert list(book.sets)[-1] == "mine"
    assert book.own()[0].rules == RULES
    assert book.sets["mine"].languages == ()  # one rule has no language, so the set works on every one
    assert [s.name for s in book.chosen()][-1] == "mine"
    assert "ocr" not in [s.name for s in book.chosen()]


def test_a_set_whose_rules_name_languages_covers_only_those(tmp_path: Path) -> None:
    rules = (RuleDef("a", ("x",), languages=("tr",)), RuleDef("b", ("y",), languages=("en-US",)))
    (tmp_path / file_name("langs")).write_text(dump_set(RuleSet("langs", rules)), encoding="utf-8")
    langs = load_book(tmp_path).sets["langs"]
    assert langs.languages == ("en-US", "tr")
    assert [langs.covers(Language.parse(tag)) for tag in ("tr", "en", "pt-BR")] == [True, True, False]
    assert not langs.covers(None)


def test_a_broken_file_is_named_and_its_set_left_out(tmp_path: Path) -> None:
    (tmp_path / file_name("good")).write_text(dump_set(RuleSet("good", RULES)), encoding="utf-8")
    (tmp_path / file_name("syntax")).write_text("rules: [", encoding="utf-8")
    (tmp_path / file_name("regex")).write_text("rules:\n  r:\n    patterns: '('\n", encoding="utf-8")
    (tmp_path / file_name("no-sdh")).write_text(dump_set(RuleSet("no-sdh", RULES)), encoding="utf-8")
    (tmp_path / file_name("bytes")).write_bytes(b"\xff\xfe\x00")
    book = load_book(tmp_path)
    assert "good" in book.sets
    assert {p.file for p in book.problems} == {file_name(n) for n in ("syntax", "regex", "no-sdh", "bytes")}
    assert not {"syntax", "regex", "bytes"} & set(book.sets)
    assert book.sets["no-sdh"].rules[0].name != "no-ads"  # the built-in set is still cleanit's


def test_pausing_a_built_in_rule_is_written_by_its_name_and_survives_a_missing_rule(tmp_path: Path) -> None:
    name = builtin_sets()["no-sdh"].rules[0].name
    (tmp_path / file_name(PAUSES)).write_text(dump_pauses(frozenset({name, "removed-from-cleanit"})), encoding="utf-8")
    paused = [r.name for r in load_book(tmp_path).sets["no-sdh"].rules if r.paused]
    assert paused == [name]
    assert not any(r.paused for r in builtin_sets()["no-sdh"].rules)


def test_the_signature_changes_when_a_file_does(tmp_path: Path) -> None:
    before = signature(tmp_path)
    (tmp_path / file_name("a")).write_text("rules: {}", encoding="utf-8")
    assert signature(tmp_path) != before
    assert signature(tmp_path / "missing") == ()


def test_the_fingerprint_follows_the_rules_that_would_run() -> None:
    base = RuleSet("s", RULES)
    assert base.fingerprint == replace(base, name="renamed").fingerprint
    assert base.fingerprint != RuleSet("s", (replace(RULES[0], patterns=("x",)), *RULES[1:])).fingerprint
    # A paused rule changes nothing the set does.
    unpaused = RuleSet("s", (RULES[0], replace(RULES[1], paused=False), RULES[2]))
    assert base.fingerprint != unpaused.fingerprint
    assert base.fingerprint == RuleSet("s", (RULES[0], replace(RULES[1], patterns=("z",)), RULES[2])).fingerprint


def test_names_that_differ_only_in_case_are_one_file_name() -> None:
    assert (valid_name("Tidy"), valid_name("PAUSES"), valid_name("Mine")) == ("taken", "taken", "")


def test_a_file_is_read_once_until_it_changes(tmp_path: Path) -> None:
    (tmp_path / file_name("mine")).write_text(dump_set(RuleSet("mine", RULES)), encoding="utf-8")
    cache: dict = {}
    first = load_book(tmp_path, cache)
    (key,) = cache
    assert load_book(tmp_path, cache).sets["mine"] is first.sets["mine"]
    (tmp_path / file_name("mine")).write_text(dump_set(RuleSet("mine", RULES[:1])), encoding="utf-8")
    assert len(load_book(tmp_path, cache).sets["mine"].rules) == 1
    assert key not in cache
    assert len(cache) == 1
