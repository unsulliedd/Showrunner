"""Rules read from Subtitle Edit's files, as cleanit rules.

Two kinds of file hold the rules a person has built up there:

- Multiple replace: groups of rules, in the user's `Settings.xml` (`<MultipleSearchAndReplaceGroups>` with a `<Group>`
  per group: `<Name>`, `<Enabled>`, and `<Rule>` elements with `<Enabled>`, `<FindWhat>`, `<ReplaceWith>`,
  `<SearchType>` and `<Description>`) or a file exported from the dialog with the same elements. Newer versions say
  `<Active>` for `<Enabled>`; the older single list of `<MultipleSearchAndReplaceItem>` is read as one group.
- OCR fix lists, `<language>_OCRFixReplaceList.xml` in its Dictionaries folder: sections of `from`/`to` pairs.

Each group becomes an own set, and the OCR pairs become rules for the user's additions to the OCR fixes. What cannot be
carried over (rules that work only with Subtitle Edit's spelling dictionaries, regular expressions in the .NET dialect
that Python does not read) is listed with its reason.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from xml.etree import ElementTree

from showrunner.core.language import Language
from showrunner.tools.cleanit.book import valid_name
from showrunner.tools.cleanit.engine import check_rule
from showrunner.tools.cleanit.files import NAME_PATTERN
from showrunner.tools.cleanit.model import Match, RuleDef, RuleKind, RuleSet

_ELEMENTS = {"MultipleSearchAndReplaceGroups", "MultipleSearchAndReplaceList"}
_GROUP_NAME = re.compile(r"[^\w-]+")
_DOTNET_NAME = re.compile(r"\(\?<([A-Za-z_]\w*)>")
_DOTNET_BACKREF = re.compile(r"\\k<([A-Za-z_]\w*)>")
_TEMPLATE = re.compile(r"\$(\$|\d+|\{(\w+)\})")
_NAME_LENGTH = 70


@dataclass(frozen=True, slots=True)
class Skipped:
    """Something in a file that was not carried over."""

    where: str  # the group or section it was in
    text: str  # the pattern or word, as the file has it
    reason: str  # `dotnet-regex`, `spelling`, `empty`, `unknown-type`


@dataclass(frozen=True, slots=True)
class Imported:
    sets: tuple[RuleSet, ...] = ()  # one per group of a Multiple replace file
    ocr: tuple[RuleDef, ...] = ()  # to join the user's additions to the OCR fixes
    skipped: tuple[Skipped, ...] = ()

    @property
    def rules(self) -> int:
        return sum(len(s.rules) for s in self.sets) + len(self.ocr)


class NotSubtitleEditError(ValueError):
    """The file is no Multiple replace or OCR fix file of Subtitle Edit."""


def read_file(content: bytes, taken: Iterable[str] = (), language: str = "") -> Imported:
    """The rules of a Subtitle Edit file: Multiple replace groups, or an OCR fix list (then `language`, an IETF tag
    from the file's name, is the language of its rules). `taken` are the names of sets that exist, which a group's
    name must not repeat."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise NotSubtitleEditError(str(error)) from error
    if root.tag == "OCRFixReplaceList":
        return _ocr(root, language)
    holders = [e for e in root.iter() if e.tag in _ELEMENTS]
    if not holders:
        raise NotSubtitleEditError("no rules")
    return _multiple(holders[0], set(taken))


def language_of(file_name: str) -> str:
    """`en` for `eng_OCRFixReplaceList.xml`: the language an OCR fix list's name gives, or an empty string."""
    language = Language.parse(file_name.split("_")[0]) if "_" in file_name else None
    return language.ietf if language is not None else ""


def _multiple(holder: ElementTree.Element, taken: set[str]) -> Imported:
    groups = holder.findall("Group")
    if not groups:  # the older list of items without groups
        groups = [holder]
    sets: list[RuleSet] = []
    skipped: list[Skipped] = []
    for index, group in enumerate(groups, 1):
        title = _text(group, "Name") or f"Subtitle Edit {index}"
        group_off = not _enabled(group)
        rules: list[RuleDef] = []
        items = group.findall("Rule") + group.findall("MultipleSearchAndReplaceItem")
        for item in items:
            rule, problem = _rule(item, title, {r.name for r in rules}, group_off)
            if rule is not None:
                rules.append(rule)
            elif problem is not None:
                skipped.append(problem)
        if rules:
            name = _free_name(title, taken)
            taken.add(name)
            sets.append(RuleSet(name, tuple(rules)))
    return Imported(tuple(sets), (), tuple(skipped))


def _rule(
    item: ElementTree.Element, group: str, names: set[str], group_off: bool
) -> tuple[RuleDef | None, Skipped | None]:
    find = _raw(item, "FindWhat")
    replace = _raw(item, "ReplaceWith")
    kind = _text(item, "SearchType") or "Normal"
    if not find:
        return None, Skipped(group, "", "empty")
    if kind not in ("Normal", "CaseSensitive", "RegularExpression"):
        return None, Skipped(group, find, "unknown-type")
    paused = group_off or not _enabled(item)
    name = _unique(_text(item, "Description") or find, names)
    if kind == "RegularExpression":
        pattern, template = _python_regex(find), _python_template(replace)
        if pattern is None or template is None:
            return None, Skipped(group, find, "dotnet-regex")
        return _checked(RuleDef(name, (pattern,), replacement=template, paused=paused), group, find)
    flags = ("ignorecase",) if kind == "Normal" else ()
    text = _literal(_newlines(replace))
    if _text(item, "WholeWord").casefold() == "true":
        # Text has no word edges in cleanit, so the word is a pattern with them.
        pattern = rf"(?<!\w){re.escape(_newlines(find))}(?!\w)"
        return _checked(RuleDef(name, (pattern,), flags=flags, replacement=text, paused=paused), group, find)
    return _checked(
        RuleDef(name, (_newlines(find),), RuleKind.TEXT, flags=flags, replacement=text, paused=paused), group, find
    )


def _checked(rule: RuleDef, group: str, find: str) -> tuple[RuleDef | None, Skipped | None]:
    return (rule, None) if not check_rule(rule) else (None, Skipped(group, find, "dotnet-regex"))


def _ocr(root: ElementTree.Element, language: str) -> Imported:
    # The sections that replace without asking the dictionary: whole words, parts of words and lines, line ends.
    rules: list[RuleDef] = []
    skipped: list[Skipped] = []
    names: set[str] = set()
    tags = (language,) if language else ()
    for section in root:
        for entry in section.findall("*"):
            find, replace = (
                entry.get("from") or entry.get("find") or "",
                entry.get("to") or entry.get("replaceWith") or "",
            )
            if section.tag in {"PartialWords", "PartialLines", "RegularExpressionsIfSpelledCorrectly"}:
                skipped.append(Skipped(section.tag, find, "spelling"))
                continue
            if not find:
                continue
            name = _unique(f"{section.tag}: {find}", names)
            rule = _ocr_rule(section.tag, name, find, replace, tags)
            if rule is None:
                skipped.append(
                    Skipped(
                        section.tag, find, "dotnet-regex" if section.tag == "RegularExpressions" else "unknown-type"
                    )
                )
            elif check_rule(rule):
                skipped.append(Skipped(section.tag, find, "dotnet-regex"))
            else:
                rules.append(rule)
    return Imported((), tuple(rules), tuple(skipped))


def _ocr_rule(section: str, name: str, find: str, replace: str, languages: tuple[str, ...]) -> RuleDef | None:
    text = _literal(replace)
    if section == "WholeWords":
        return RuleDef(name, (rf"(?<!\w){re.escape(find)}(?!\w)",), replacement=text, languages=languages)
    if section == "RegularExpressions":
        pattern, template = _python_regex(find), _python_template(replace)
        if pattern is None or template is None:
            return None
        return RuleDef(name, (pattern,), replacement=template, languages=languages)
    kinds = {
        "PartialWordsAlways": Match.CONTAINS,
        "PartialLinesAlways": Match.CONTAINS,
        "WholeLines": Match.EXACT,
        "BeginLines": Match.STARTSWITH,
        "EndLines": Match.ENDSWITH,
    }
    if section not in kinds:
        return None
    return RuleDef(name, (find,), RuleKind.TEXT, kinds[section], text, languages)


def _python_regex(pattern: str) -> str | None:
    """A .NET regular expression as Python's, for the parts that differ in spelling; None when it still does not
    compile there (constructs only .NET has)."""
    converted = _DOTNET_BACKREF.sub(r"(?P=\1)", _DOTNET_NAME.sub(r"(?P<\1>", pattern)).replace(r"\z", r"\Z")
    return converted if not check_rule(RuleDef("check", (converted,))) else None


def _python_template(replacement: str) -> str | None:
    """A .NET replacement (`$1`, `${name}`, `$$`) as Python's (`\\g<1>`, `\\g<name>`, `$`)."""

    def group(match: re.Match[str]) -> str:
        token = match.group(1)
        return "$" if token == "$" else rf"\g<{match.group(2) or token}>"

    return _TEMPLATE.sub(group, _newlines(replacement).replace("\\", "\\\\"))


def _literal(text: str) -> str:
    """Text as a replacement that is taken literally: cleanit reads backslashes in it."""
    return text.replace("\\", "\\\\")


def _newlines(text: str) -> str:
    return text.replace("\\r\\n", "\n").replace("\\n", "\n")


def _free_name(title: str, taken: set[str]) -> str:
    base = _GROUP_NAME.sub("-", title).strip("-")[:30] or "subtitle-edit"
    name, number = base, 1
    folded = {existing.casefold() for existing in taken}
    while valid_name(name) or name.casefold() in folded or not NAME_PATTERN.fullmatch(name):
        number += 1
        name = f"{base}-{number}"
    return name


def _unique(text: str, names: set[str]) -> str:
    base = " ".join(text.split())[:_NAME_LENGTH] or "rule"
    name, number = base, 1
    while name in names:
        number += 1
        name = f"{base} ({number})"
    names.add(name)
    return name


def _raw(element: ElementTree.Element, tag: str) -> str:
    found = element.find(tag)
    return found.text or "" if found is not None else ""


def _text(element: ElementTree.Element, tag: str) -> str:
    return _raw(element, tag).strip()


def _enabled(element: ElementTree.Element) -> bool:
    """Whether an element is switched on: its `Enabled` (or `Active`) child, on when it has none."""
    for name in ("Enabled", "Active"):
        value = element.find(name)
        if value is not None and value.text is not None:
            return value.text.strip().casefold() == "true"
    return True
