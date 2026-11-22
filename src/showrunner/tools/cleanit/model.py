"""The cleanup rules as the app holds them: plain values, written to and read from cleanit's YAML by `files`."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

from showrunner.core.language import Language


class RuleKind(StrEnum):
    TEXT = "text"  # the pattern is plain text
    REGEX = "regex"  # the pattern is a regular expression


class Match(StrEnum):
    """How much of the text a pattern has to cover; a text rule that should find a word anywhere uses `CONTAINS`."""

    CONTAINS = "contains"
    EXACT = "exact"
    STARTSWITH = "startswith"
    ENDSWITH = "endswith"


@dataclass(frozen=True, slots=True)
class Example:
    """Sample text a rule is written for, and what it becomes; `after` is None for text the rule drops."""

    before: str
    after: str | None = None


@dataclass(frozen=True, slots=True)
class RuleDef:
    """One rule, with the fields cleanit's YAML has for it."""

    name: str
    patterns: tuple[str, ...]
    kind: RuleKind = RuleKind.REGEX
    match: Match = Match.CONTAINS
    # What replaces the matched part; empty deletes it. None drops the whole line: every row of text shown at that
    # time, since cleanit runs a rule on the lines of a cue joined.
    replacement: str | None = None
    languages: tuple[str, ...] = ()  # IETF tags; none means every language
    priority: int = 0  # the rule with the higher one runs first
    flags: tuple[str, ...] = ()
    examples: tuple[Example, ...] = ()
    paused: bool = False  # `disabled` in cleanit's YAML

    @property
    def drops(self) -> bool:
        return self.replacement is None

    def covers(self, language: Language | None) -> bool:
        """Whether the rule works on text in `language`: a rule without languages on every one, and a rule with them on
        the languages of the same primary language, as cleanit matches them. A subtitle of no known language gets the
        rules without languages only."""
        if not self.languages:
            return True
        if language is None:
            return False
        return language.alpha3 in language_codes(self.languages)


@dataclass(frozen=True, slots=True)
class RuleSet:
    """The rules that cleanit's YAML tags with one name, and what the app needs of them to choose and show the set."""

    name: str
    rules: tuple[RuleDef, ...] = ()
    builtin: bool = False
    # Words that stand for character ranges inside patterns, such as `[:upper:]`, which the YAML of an own set may
    # define for itself.
    aliases: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def languages(self) -> tuple[str, ...]:
        """The IETF tags the set works on, sorted; none means it works on every language."""
        if not self.rules or any(not rule.languages for rule in self.rules):
            return ()
        return tuple(sorted({tag for rule in self.rules for tag in rule.languages}))

    def covers(self, language: Language | None) -> bool:
        """Whether some unpaused rule works on `language`, so cleaning with the set can change a subtitle in it."""
        return any(not rule.paused and rule.covers(language) for rule in self.rules)

    @property
    def fingerprint(self) -> str:
        """Changes whenever a rule that would run changes, so a result cleaned with the old rules is not reused."""
        text = repr([rule for rule in self.rules if not rule.paused])
        return hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()


def language_codes(tags: tuple[str, ...]) -> frozenset[str]:
    """The ISO 639-3 codes of IETF tags; a tag that is no language is left out."""
    return frozenset(language.alpha3 for tag in tags if (language := Language.parse(tag)) is not None)
