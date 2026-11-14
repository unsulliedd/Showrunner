"""Checking the user's track rules, for the editor that lists them and for deciding whether the stage can run."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from showrunner.core.language import Language
from showrunner.stages.tracks.matching import NO_LANGUAGE
from showrunner.stages.tracks.options import TracksOptions


class RuleField(StrEnum):
    LANGUAGES = "languages"
    CHANNELS = "channels"
    NAME = "name"


class RuleProblemKind(StrEnum):
    NOT_A_LANGUAGE = "not-a-language"  # detail: the entry
    BAD_PATTERN = "bad-pattern"  # detail: the regular expression error
    EMPTY_CHANNEL_RANGE = "empty-channel-range"  # the low end is above the high end, so no track fits


@dataclass(frozen=True, slots=True)
class RuleProblem:
    """A problem in rule `rule_index`. For a list field, `entry` is the position of the entry at fault and
    `start`/`end` lie inside that entry; for the name, `start`/`end` lie inside the pattern."""

    rule_index: int
    field: RuleField
    kind: RuleProblemKind
    start: int = 0
    end: int = 0
    detail: str = ""
    entry: int | None = None


def check_rules(options: TracksOptions) -> list[RuleProblem]:
    """Every problem in every rule, switched on or not, in rule order; empty when all is well. Each problem
    makes a part of the rule fit nothing, which is never what the rule was written for."""
    found: list[RuleProblem] = []
    for index, rule in enumerate(options.rules):
        match = rule.match
        for entry, text in enumerate(match.languages):
            tag = text.strip()
            if tag and tag.casefold() != NO_LANGUAGE and Language.parse(tag) is None:
                found.append(
                    RuleProblem(index, RuleField.LANGUAGES, RuleProblemKind.NOT_A_LANGUAGE, 0, len(text), tag, entry)
                )
        if match.max_channels and match.min_channels > match.max_channels:
            found.append(RuleProblem(index, RuleField.CHANNELS, RuleProblemKind.EMPTY_CHANNEL_RANGE))
        if match.name and match.name_is_regex:
            try:
                re.compile(match.name, re.IGNORECASE)
            except re.error as error:
                start = error.pos if error.pos is not None else 0
                found.append(
                    RuleProblem(index, RuleField.NAME, RuleProblemKind.BAD_PATTERN, start, len(match.name), error.msg)
                )
    return found
