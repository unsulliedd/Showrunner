"""Cleaning text with cleanit's rules. Cleanit is a library, but it is reached through this one adapter as the external
programs are: it is imported when first needed, so a cleanit that fails to load (its own configuration folder holds a
broken file) turns off cleanup and nothing else.

The rules run on the text of a cue as a SubRip file has it, where italics are `<i>`; cues carry them as the
`{\\i1}` overrides, so the text is converted around the call.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any

import yaml

from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.tools.cleanit.model import RuleDef, RuleSet

# The most rule applications to one text, and how much longer than the original it may become, before the rules are
# taken to loop.
_MAX_STEPS = 200
_GROWTH = 4
_SLACK = 200
_OVERRIDE_ON = re.compile(r"\{\\([ibus])1\}")
_OVERRIDE_OFF = re.compile(r"\{\\([ibus])0\}")
_TAG_ON = re.compile(r"<([ibus])>")
_TAG_OFF = re.compile(r"</([ibus])>")


class CleanitUnavailableError(RuntimeError):
    """Cleanit could not be loaded."""


class RuleError(ValueError):
    """A rule cleanit cannot build, with what is wrong with it."""


class RuleLoopError(RuntimeError):
    """Rules that keep matching the text they produce: cleanit applies them again until Python's recursion ends."""


def cleanit_module(name: str = "") -> ModuleType:
    """A module of the cleanit package, imported on first use. Importing the package reads the user's cleanit
    configuration folders, and a broken file there makes the import fail."""
    try:
        return importlib.import_module(f"cleanit.{name}" if name else "cleanit")
    except Exception as error:  # the package runs user-supplied YAML while it loads
        raise CleanitUnavailableError(str(error)) from error


@lru_cache(maxsize=1)
def builtin_aliases() -> dict[str, str]:
    """The words cleanit's own rules use for character ranges (`[:upper:]`)."""
    data = pkgutil.get_data("cleanit", "data/cleanit.yml")
    return dict((yaml.safe_load(data) or {}).get("aliases", {})) if data else {}


def compile_rule(rule: RuleDef, aliases: Mapping[str, str] | None = None) -> Any:
    """Cleanit's own rule object for a rule. Raises `RuleError` for a pattern that does not compile or a replacement
    that names a group the pattern lacks."""
    if not any(rule.patterns) or not all(rule.patterns):
        raise RuleError("a pattern is empty")
    words = {**builtin_aliases(), **(aliases or {})}
    try:
        built = cleanit_module("rule").Rule(
            name=rule.name,
            aliases=words,
            patterns=list(rule.patterns),
            type=rule.kind.value,
            match=rule.match.value,
            priority=rule.priority,
            flags=list(rule.flags),
            replacement=rule.replacement,
        )
        if rule.replacement:
            for regex in built.regexes:
                regex.sub(rule.replacement, "")  # a template naming a missing group fails here, not on a match
    except (re.error, IndexError) as error:
        raise RuleError(str(error)) from error
    return built


def check_rule(rule: RuleDef, aliases: Mapping[str, str] | None = None) -> str:
    """What is wrong with a rule, or an empty string."""
    try:
        compile_rule(rule, aliases)
    except RuleError as error:
        return str(error)
    return ""


@dataclass(frozen=True, slots=True)
class CompiledRules:
    """The rules of some sets for one language, ready to run in the order cleanit runs them."""

    rules: tuple[Any, ...]  # cleanit's `Rule` objects, in the order they are tried
    count: int


@dataclass(frozen=True, slots=True)
class CueResult:
    """A cue and what the rules made of it."""

    cue: Cue
    text: str | None  # None: the rules drop the cue
    rules: tuple[str, ...] = ()  # the rules that acted on it, in order
    looped: bool = False  # the rules never settled on a text (`RuleLoopError`), so the cue is left as it was

    @property
    def dropped(self) -> bool:
        return self.text is None

    @property
    def changed(self) -> bool:
        return self.text is not None and self.text != self.cue.text

    @property
    def kept(self) -> Cue | None:
        return None if self.text is None else Cue(self.cue.start, self.cue.end, self.text, self.cue.style)


def compile_sets(sets: Iterable[RuleSet], language: Language | None) -> CompiledRules:
    """The unpaused rules of the sets that work on `language`, the higher priority first and rules of one priority in
    the order the sets and files give them. Raises `RuleError` for a rule that cannot be built."""
    chosen: list[tuple[RuleDef, RuleSet]] = [
        (rule, rule_set) for rule_set in sets for rule in rule_set.rules if not rule.paused and rule.covers(language)
    ]
    chosen.sort(key=lambda pair: -pair[0].priority)  # stable: ties keep their order
    built = [compile_rule(rule, rule_set.aliases) for rule, rule_set in chosen]
    return CompiledRules(tuple(built), len(built))


def clean_text(text: str, compiled: CompiledRules) -> tuple[str | None, tuple[str, ...]]:
    """The text after the rules, or None when they drop it, and the names of the rules that acted on it. Raises
    `RuleLoopError` for rules that never settle.

    Cleanit's own loop does the same (the first rule that matches is applied until it no longer matches, then every
    rule is tried again), but it recurses without limit, and a replacement that contains its own pattern grows the
    text at every step. This loop stops at a number of steps and a text length."""
    if not compiled.count:
        return text, ()
    current: str | None = _as_tags(text)
    names: list[str] = []
    limit = len(text) * _GROWTH + _SLACK
    for _ in range(_MAX_STEPS):
        for rule in compiled.rules:
            matched, value = _apply(rule, current)
            if matched:
                names.append(rule.name)
                current = value
                break
        else:
            return _finish(text, current, names)
        if not current:
            return None, tuple(dict.fromkeys(names))
        if len(current) > limit:
            raise RuleLoopError(text)
    raise RuleLoopError(text)


def _apply(rule: Any, text: str) -> tuple[bool, str | None]:
    """One application of a cleanit rule: whether it matched, and the text it leaves (None: the cue is dropped)."""
    for regex in rule.regexes:
        if regex.search(text):
            if rule.replacement is None:
                return True, None
            return True, regex.sub(rule.replacement, text).strip() or None
    return False, text


def _finish(text: str, current: str | None, names: list[str]) -> tuple[str | None, tuple[str, ...]]:
    if not names:
        return text, ()
    changed = _as_overrides(current) if current else None
    return changed, tuple(dict.fromkeys(names))


def clean_cues(cues: Sequence[Cue], compiled: CompiledRules) -> list[CueResult]:
    results = []
    for cue in cues:
        try:
            results.append(CueResult(cue, *clean_text(cue.text, compiled)))
        except RuleLoopError:
            results.append(CueResult(cue, cue.text, looped=True))
    return results


def kept_cues(results: Iterable[CueResult]) -> list[Cue]:
    """The cues the rules leave, cleaned."""
    return [kept for result in results if (kept := result.kept) is not None]


def _as_tags(text: str) -> str:
    return _OVERRIDE_OFF.sub(r"</\1>", _OVERRIDE_ON.sub(r"<\1>", text))


def _as_overrides(text: str) -> str:
    return _TAG_OFF.sub(r"{\\\g<1>0}", _TAG_ON.sub(r"{\\\g<1>1}", text))
