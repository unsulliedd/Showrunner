"""Cleaning text with cleanit's rules, through the adapter."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.tools.cleanit import (
    BUILTIN_ORDER,
    RuleBook,
    RuleDef,
    RuleError,
    RuleKind,
    RuleLoopError,
    RuleSet,
    builtin_sets,
    check_rule,
    clean_cues,
    clean_text,
    kept_cues,
    load_book,
)
from showrunner.tools.cleanit.engine import cleanit_module, compile_sets

ENGLISH = Language("eng")


def overrides(text: str) -> str:
    """A SubRip example's `<i>` as the cue text has it."""
    text = re.sub(r"<([ibus])>", lambda m: "{\\" + m[1] + "1}", text)
    return re.sub(r"</([ibus])>", lambda m: "{\\" + m[1] + "0}", text)


def examples() -> list[tuple[str, RuleSet, RuleDef]]:
    return [(rule.name, rule_set, rule) for rule_set in builtin_sets().values() for rule in rule_set.rules]


def test_the_built_in_sets_are_cleanits_in_a_fixed_order() -> None:
    assert tuple(builtin_sets()) == BUILTIN_ORDER
    assert all(s.builtin and s.rules for s in builtin_sets().values())


@pytest.mark.parametrize(("name", "rule_set", "rule"), examples(), ids=[e[0] for e in examples()])
def test_every_built_in_rule_does_what_its_examples_say(name: str, rule_set: RuleSet, rule: RuleDef) -> None:
    language = Language.parse(rule.languages[0]) if rule.languages else ENGLISH
    compiled = compile_sets([replace(rule_set, rules=(rule,))], language)
    for example in rule.examples:
        text, rules = clean_text(overrides(example.before.strip()), compiled)
        expected = None if example.after is None else overrides(example.after.strip())
        assert text == expected, example.before
        # An example that shows text the rule leaves alone has no rule that acted.
        assert rules == ((name,) if expected != overrides(example.before.strip()) else ())


def test_a_rule_works_on_the_languages_it_names_only() -> None:
    sets = [RuleSet("x", (RuleDef("r", ("a",), replacement="b", languages=("pt",)),))]
    assert clean_text("a", compile_sets(sets, Language("por")))[0] == "b"
    assert clean_text("a", compile_sets(sets, Language.parse("pt-BR")))[0] == "b"
    assert clean_text("a", compile_sets(sets, ENGLISH)) == ("a", ())
    assert clean_text("a", compile_sets(sets, None)) == ("a", ())


def test_rules_run_by_priority_and_a_paused_rule_does_not_run() -> None:
    first = RuleDef("first", ("a",), replacement="b", priority=5)
    second = RuleDef("second", ("b",), replacement="c")
    text, rules = clean_text("a", compile_sets([RuleSet("x", (second, first))], ENGLISH))
    assert (text, rules) == ("c", ("first", "second"))
    paused = replace(first, paused=True)
    assert clean_text("a", compile_sets([RuleSet("x", (second, paused))], ENGLISH)) == ("a", ())


def test_a_rule_without_a_replacement_drops_the_whole_cue_and_an_empty_one_deletes_the_match() -> None:
    rules = [
        RuleSet("x", (RuleDef("drop", ("ad",), RuleKind.TEXT), RuleDef("cut", ("zz",), replacement=""))),
    ]
    compiled = compile_sets(rules, ENGLISH)
    results = clean_cues([Cue(0, 1, "hello\nad here"), Cue(1, 2, "keep zz it"), Cue(2, 3, "plain")], compiled)
    assert [(r.dropped, r.changed, r.rules) for r in results] == [
        (True, False, ("drop",)),
        (False, True, ("cut",)),
        (False, False, ()),
    ]
    assert [c.text for c in kept_cues(results)] == ["keep  it", "plain"]


def test_styling_survives_a_change_and_is_seen_by_the_rules() -> None:
    sets = builtin_sets()
    cue = Cue(0, 1, r"{\i1}Oh,  well{\i0}")
    (result,) = clean_cues([cue], compile_sets([sets["tidy"]], ENGLISH))
    assert result.text == r"{\i1}Oh, well{\i0}"
    (result,) = clean_cues([cue], compile_sets([sets["no-style"]], ENGLISH))
    assert result.text == "Oh,  well"


def test_a_rule_that_cannot_be_built_says_why() -> None:
    assert check_rule(RuleDef("ok", ("a+",))) == ""
    assert "unterminated" in check_rule(RuleDef("bad", ("(",)))
    assert check_rule(RuleDef("none", ()))
    assert "group" in check_rule(RuleDef("group", ("(a)",), replacement=r"\g<missing>"))
    with pytest.raises(RuleError):
        compile_sets([RuleSet("x", (RuleDef("bad", ("(",)),))], ENGLISH)


def test_the_words_for_character_ranges_work_in_an_own_rule() -> None:
    rule = RuleDef("caps", (r"^[[:upper:]]+$",), replacement="x")
    assert clean_text("ABC", compile_sets([RuleSet("x", (rule,))], ENGLISH))[0] == "x"


def test_a_book_without_a_folder_has_the_built_in_sets_only() -> None:
    book = load_book(None)
    assert isinstance(book, RuleBook)
    assert tuple(book.sets) == BUILTIN_ORDER
    assert book.problems == ()
    assert book.known(["no-sdh", "gone"]) == (book.sets["no-sdh"],)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("f I'm going down to the river, I", "♪ I'm going down to the river, I"),
        ('~ People spouting,\n"howdy, neighbor" f', '♪ People spouting,\n"howdy, neighbor" ♪'),
        ("£ Smokin' f", "♪ Smokin' ♪"),
        ("Heading on up\nto the river ~", "Heading on up\nto the river ♪"),
    ],
)
def test_the_ocr_fixes_turn_a_misread_music_note_into_one(before: str, after: str) -> None:
    assert clean_text(before, load_book(None).ocr(ENGLISH))[0] == after


@pytest.mark.parametrize(
    "text",
    [
        "The f word, f.",
        "of f-stops and fun",
        "It costs ~5 now",
        "£10 for this",
        "Say the letter f.",
        "If I go",
        "Half ~ half",
    ],
)
def test_the_music_note_fix_leaves_real_words_alone(text: str) -> None:
    (music,) = (rule for rule in builtin_sets()["ocr"].rules if rule.name == "music-note")
    assert clean_text(text, compile_sets([RuleSet("x", (music,))], ENGLISH)) == (text, ())


def test_rules_that_never_settle_leave_the_cue_as_it_was_and_say_so() -> None:
    grows = RuleSet("x", (RuleDef("grow", ("a",), RuleKind.TEXT, replacement="aa"),))
    compiled = compile_sets([grows], ENGLISH)
    with pytest.raises(RuleLoopError):
        clean_text("a", compiled)
    (result,) = clean_cues([Cue(0, 1, "a")], compiled)
    assert (result.looped, result.changed, result.dropped, result.text) == (True, False, False, "a")


@pytest.mark.parametrize("language", ["en", "pt", "tr"])
def test_the_loop_gives_what_cleanits_own_does_for_every_built_in_set(language: str) -> None:
    """The loop is cleanit's with a limit: on text that settles, the two end in the same place."""
    spoken = Language.parse(language)
    for name, rule_set in builtin_sets().items():
        compiled = compile_sets([rule_set], spoken)
        theirs = cleanit_module("rule").Rules(rules=list(compiled.rules), tags={"all"})
        texts = [e.before.strip() for r in rule_set.rules for e in r.examples]
        texts += ["Hello  world ,there", "- (SNICKERS)\n- Hi", "♪ la la ♪", "  ", "..", "A -B"]
        for text in texts:
            result, modified = theirs.apply(text)
            expected = (overrides(result) if result else None) if modified else overrides(text)
            assert clean_text(overrides(text), compiled)[0] == expected, (name, text)
