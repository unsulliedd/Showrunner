"""Rule sets as cleanit's YAML files: reading a file into rules, and writing rules back so that cleanit itself reads
them. The files are UTF-8 and use cleanit's own keys, so a set stays usable with cleanit's command line."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml
from jsonschema import ValidationError

from showrunner.tools.cleanit.engine import cleanit_module
from showrunner.tools.cleanit.model import Example, Match, RuleDef, RuleKind, RuleSet

FILE_PREFIX = "cleanit-"
FILE_SUFFIX = ".yml"
# What an own set may be called: it is the name of its file and the tag of its rules.
NAME_PATTERN = re.compile(r"[\w-]{1,40}")


class RulesFileError(ValueError):
    """A rules file that cleanit would not read, with what is wrong with it."""


@dataclass(frozen=True, slots=True)
class ParsedFile:
    rules: tuple[RuleDef, ...]
    aliases: dict[str, str]
    # The names of rules the file only pauses (or unpauses), without defining them: how a built-in rule is paused.
    paused: frozenset[str] = frozenset()


def file_name(set_name: str) -> str:
    return f"{FILE_PREFIX}{set_name}{FILE_SUFFIX}"


def set_name_of(file: str) -> str | None:
    """The set a file name stands for, or None when it is not the file of a set."""
    if not (file.startswith(FILE_PREFIX) and file.endswith(FILE_SUFFIX)):
        return None
    name = file[len(FILE_PREFIX) : -len(FILE_SUFFIX)]
    return name if NAME_PATTERN.fullmatch(name) else None


def parse_file(text: str) -> ParsedFile:
    """The rules of a cleanit YAML file. Raises `RulesFileError` when the text is no YAML, does not follow cleanit's
    schema or holds a rule cleanit could not build."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise RulesFileError(str(error)) from error
    if not isinstance(data, dict):
        raise RulesFileError("not a cleanit rules file")
    _validate(data)
    rules, paused = [], set()
    for name, body in (data.get("rules") or {}).items():
        body = body or {}
        if "patterns" not in body:
            # Cleanit merges a rule by name over the one it already has, so this entry changes only what it states.
            if body.get("disabled"):
                paused.add(str(name))
            continue
        rules.append(_rule(str(name), body))
    aliases = {str(k): str(v) for k, v in (data.get("aliases") or {}).items()}
    return ParsedFile(tuple(rules), aliases, frozenset(paused))


def dump_set(rule_set: RuleSet) -> str:
    """The YAML of an own set: its rules tagged with its name, and the aliases its patterns use."""
    document: dict[str, Any] = {}
    if rule_set.aliases:
        document["aliases"] = dict(rule_set.aliases)
    document["rules"] = {rule.name: _body(rule, rule_set.name) for rule in rule_set.rules}
    return _dump(document)


def dump_pauses(names: frozenset[str]) -> str:
    """The YAML that pauses built-in rules by name."""
    return _dump({"rules": {name: {"disabled": True} for name in sorted(names)}})


def _dump(document: Mapping[str, Any]) -> str:
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=120, default_flow_style=False)


def _validate(data: dict[str, Any]) -> None:
    try:
        cleanit_module("utils").validate(data)
    except ValidationError as error:
        raise RulesFileError(error.message) from error


def _rule(name: str, body: dict[str, Any]) -> RuleDef:
    patterns = body["patterns"]
    kind = RuleKind(body.get("type", RuleKind.REGEX.value))
    return RuleDef(
        name=name,
        patterns=tuple(str(p) for p in ([patterns] if isinstance(patterns, str) else patterns)),
        kind=kind,
        match=Match(body.get("match", Match.CONTAINS.value)),
        replacement=body.get("replacement"),
        languages=_strings(body.get("languages")),
        priority=int(body.get("priority", 0)),
        flags=_strings(body.get("flags")),
        examples=_examples(body.get("examples")),
        paused=bool(body.get("disabled")),
    )


def _strings(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    return (str(value),) if isinstance(value, str) else tuple(str(v) for v in value)


def _examples(value: Any) -> tuple[Example, ...]:
    if isinstance(value, dict):
        return tuple(Example(str(k), None if v is None else str(v)) for k, v in value.items())
    if isinstance(value, list):
        return tuple(Example(str(v)) for v in value)
    return ()


def _body(rule: RuleDef, set_name: str) -> dict[str, Any]:
    body: dict[str, Any] = {"tags": [set_name]}
    if rule.kind is not RuleKind.REGEX:
        body["type"] = rule.kind.value
    if rule.match is not Match.CONTAINS:
        body["match"] = rule.match.value
    if rule.priority:
        body["priority"] = rule.priority
    if rule.flags:
        body["flags"] = list(rule.flags)
    if rule.languages:
        body["languages"] = list(rule.languages)
    body["patterns"] = list(rule.patterns)
    if rule.replacement is not None:
        body["replacement"] = rule.replacement
    if rule.paused:
        body["disabled"] = True
    if rule.examples:
        body["examples"] = {example.before: example.after for example in rule.examples}
    return body
