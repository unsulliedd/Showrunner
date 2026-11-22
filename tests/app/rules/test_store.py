"""The user's rule sets in the data folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.app.rules import RuleStore
from showrunner.tools.cleanit import PAUSES, RuleDef, RuleSet, builtin_sets, file_name

RULE = RuleDef("fix", ("a",), replacement="b")


@pytest.fixture
def store(tmp_path: Path) -> RuleStore:
    return RuleStore(lambda: tmp_path / "rules")


def test_a_saved_set_is_read_back_and_a_deleted_one_is_gone(store: RuleStore) -> None:
    store.save(RuleSet("mine", (RULE,)))
    assert (store.folder / file_name("mine")).is_file()
    assert store.book().sets["mine"].rules == (RULE,)
    store.delete("mine")
    assert "mine" not in store.book().sets


def test_a_built_in_set_cannot_be_written_or_deleted(store: RuleStore) -> None:
    with pytest.raises(ValueError, match="built-in"):
        store.save(builtin_sets()["tidy"])
    for name in ("tidy", PAUSES, "a b"):
        with pytest.raises(ValueError, match=r"taken|characters"):
            store.save(RuleSet(name, (RULE,)))
    store.delete("tidy")
    assert "tidy" in store.book().sets


def test_a_file_edited_by_hand_is_read_when_it_changes(store: RuleStore) -> None:
    store.save(RuleSet("mine", (RULE,)))
    store.book()
    revision = store.revision
    assert store.book() is store.book()
    assert store.revision == revision
    (store.folder / file_name("mine")).write_text("rules:\n  other:\n    patterns: x\n    replacement: y\n", "utf-8")
    assert [r.name for r in store.book().sets["mine"].rules] == ["other"]
    assert store.revision == revision + 1


def test_pausing_a_built_in_rule_writes_its_name_and_unpausing_removes_the_file(store: RuleStore) -> None:
    name = builtin_sets()["tidy"].rules[0].name
    store.pause_builtin(name, True)
    assert [r.name for r in store.book().sets["tidy"].rules if r.paused] == [name]
    store.pause_builtin(name, False)
    assert not any(r.paused for r in store.book().sets["tidy"].rules)
    assert not (store.folder / file_name(PAUSES)).exists()


def test_two_paused_rules_stay_paused_while_one_is_unpaused(store: RuleStore) -> None:
    first, second = (r.name for r in builtin_sets()["tidy"].rules[:2])
    store.pause_builtin(first, True)
    store.pause_builtin(second, True)
    store.pause_builtin(first, False)
    assert [r.name for r in store.book().sets["tidy"].rules if r.paused] == [second]
