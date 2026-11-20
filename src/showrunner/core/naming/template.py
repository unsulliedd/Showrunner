"""Template text to a parsed tree to a name.

Syntax: `{token}`, `{token:00}` (zero padding, numbers only), `[optional group]`, and a backslash before
any character to write it literally. A group is left out when a token directly inside it is empty.

A template is a row of pieces: tokens, separators and typed text. The join character the template chose goes in
by itself between two neighbouring pieces when the left one joins after it and the right one joins before it. A token
joins on both sides, typed text on neither (it stays attached to what is next to it), and a separator has its own
sides, see `SEPARATORS`. A space typed in the template is a space of the name, so it becomes the join character too.

To write a literal `{`, `}`, `[` or `]`, put a backslash before it: `\\{`, `\\}`, `\\[`, `\\]`. A literal
backslash is `\\\\`. Brackets cannot be doubled instead, since `[[` opens a group inside a group.

Mistakes never raise. `parse` keeps the text readable and records the syntax problems; `render` adds what
only a file can tell (unknown tokens, a spec on a text token, cycles, bad patterns). Each problem carries
the position of the part at fault, and a broken token renders as empty.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from showrunner.core.naming.custom import CustomKind, CustomToken, PatternSource
from showrunner.core.naming.tokens import TOKENS, NamingContext


class ProblemKind(StrEnum):
    UNKNOWN_TOKEN = "unknown-token"  # detail: the name
    EMPTY_TOKEN = "empty-token"
    BAD_FORMAT = "bad-format"  # detail: the spec
    UNCLOSED_BRACE = "unclosed-brace"
    UNEXPECTED_CLOSE_BRACE = "unexpected-close-brace"
    UNCLOSED_GROUP = "unclosed-group"
    UNEXPECTED_CLOSE_GROUP = "unexpected-close-group"
    TRAILING_ESCAPE = "trailing-escape"
    # Defined tokens. At a use, the position is the `{token}` in the template being previewed, whatever
    # went wrong inside the token; the detail says what.
    CYCLE = "cycle"  # detail: the chain, `a > b > a`
    BAD_PATTERN = "bad-pattern"  # detail: the regular expression error
    PATTERN_WITHOUT_GROUP = "pattern-without-group"
    SHADOWS_BUILTIN = "shadows-builtin"  # detail: the name; the built-in is used
    NOT_HERE = "not-here"  # detail: the name; a token the template it is typed in cannot use
    INVALID_NAME = "invalid-name"  # definitions only
    DUPLICATE_NAME = "duplicate-name"  # definitions only; the first definition is used


@dataclass(frozen=True, slots=True)
class Problem:
    """A mistake in a template: `text[start:end]` is the part at fault."""

    kind: ProblemKind
    start: int
    end: int
    detail: str = ""


@dataclass(frozen=True, slots=True)
class _Field:
    name: str  # lower case; empty for `{}`
    padding: int  # width of a zero-padding spec, 0 without one
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Group:
    nodes: tuple[_Node, ...]


type _Node = str | _Field | _Group

# The separators: the characters a template holds as separator chips, and whether the join character goes before and
# after each. A run of literal text made of these characters only is one separator per character; a run with any other
# character in it, a space included, is typed text.
SEPARATORS: dict[str, tuple[bool, bool]] = {
    "-": (True, True),
    ".": (False, False),
    "_": (False, False),
    "(": (True, False),
    "[": (True, False),
    "{": (True, False),
    ")": (False, True),
    "]": (False, True),
    "}": (False, True),
}

# What one piece writes and whether the join character may go before it and after it.
type _Atom = tuple[str, bool, bool]
# Stands where a token had no value or a group was left out, so that separators around it can see something was there.
_NOTHING: _Atom = ("", False, False)
_CLOSERS = {")": "(", "]": "[", "}": "{"}


def separators_in(text: str) -> bool:
    """Whether the literal `text` is made of separators alone."""
    return bool(text) and all(char in SEPARATORS for char in text)


# A typed space is written as this stand-in until the name is tidied, so that the join character the template
# chose replaces it afterwards, and two spaces left side by side by an empty token still make one.
_GAP = "\ue000"
_BLANK = rf"[\s{_GAP}]"

# Parentheses left empty or padded by an empty token inside them; blanks left side by side become one.
_TIDY = (
    (re.compile(rf"\({_BLANK}+"), "("),
    (re.compile(rf"{_BLANK}+\)"), ")"),
    (re.compile(r"\(\)"), ""),
    (re.compile(rf"{_BLANK}{{2,}}"), lambda found: _GAP if _GAP in found[0] else " "),
)
_BLANK_ENDS = re.compile(rf"^{_BLANK}+|{_BLANK}+$")


def _tidy(text: str, context: NamingContext) -> str:
    """The name without the blanks and parentheses that empty tokens left, its gaps written with the join character."""
    for pattern, replacement in _TIDY:
        text = pattern.sub(replacement, text)
    return _BLANK_ENDS.sub("", text).replace(_GAP, context.space.character)


@dataclass(frozen=True, slots=True)
class Preview:
    text: str
    problems: tuple[Problem, ...]


@dataclass(frozen=True, slots=True)
class Template:
    nodes: tuple[_Node, ...]
    problems: tuple[Problem, ...]  # syntax problems only

    def render(self, context: NamingContext) -> Preview:
        problems = list(self.problems)
        atoms, _ = _render(self.nodes, context, (), problems, None)
        return Preview(_tidy(_assemble(atoms), context), tuple(sorted(problems, key=lambda p: p.start)))


def preview(template: str, context: NamingContext) -> Preview:
    """What the template makes of this file, and what is wrong with it; for the editor."""
    return parse(template).render(context)


# A plan renders the same few templates for every file and track; the parsed template is immutable, so it is shared.
@lru_cache(maxsize=256)
def parse(text: str) -> Template:
    problems: list[Problem] = []
    # Open groups as (position of its `[`, its nodes); the first entry is the template itself.
    stack: list[tuple[int, list[_Node]]] = [(-1, [])]
    literal: list[str] = []

    def flush() -> None:
        if literal:
            stack[-1][1].append("".join(literal))
            literal.clear()

    def close_group() -> None:
        flush()
        _, inner = stack.pop()
        stack[-1][1].append(_Group(tuple(inner)))

    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            if i + 1 < len(text):
                literal.append(text[i + 1])
                i += 2
                continue
            problems.append(Problem(ProblemKind.TRAILING_ESCAPE, i, i + 1))
            literal.append(char)
        elif char == "{":
            end = text.find("}", i + 1)
            # A second `{` before the `}` means the first was never closed.
            if end == -1 or "{" in text[i + 1 : end]:
                problems.append(Problem(ProblemKind.UNCLOSED_BRACE, i, i + 1))
                literal.append(char)
            else:
                flush()
                stack[-1][1].append(_read_field(text[i + 1 : end], i, end + 1, problems))
                i = end + 1
                continue
        elif char == "}":
            problems.append(Problem(ProblemKind.UNEXPECTED_CLOSE_BRACE, i, i + 1))
            literal.append(char)
        elif char == "[":
            flush()
            stack.append((i, []))
        elif char == "]":
            if len(stack) == 1:
                problems.append(Problem(ProblemKind.UNEXPECTED_CLOSE_GROUP, i, i + 1))
                literal.append(char)
            else:
                close_group()
        else:
            literal.append(char)
        i += 1

    while len(stack) > 1:
        problems.append(Problem(ProblemKind.UNCLOSED_GROUP, stack[-1][0], stack[-1][0] + 1))
        close_group()
    flush()
    return Template(tuple(stack[0][1]), tuple(problems))


class PieceKind(StrEnum):
    TEXT = "text"
    CHIP = "chip"  # a separator, see `SEPARATORS`
    TOKEN = "token"
    OPEN = "open"  # the `[` of a group
    CLOSE = "close"  # its `]`


@dataclass(frozen=True, slots=True)
class Piece:
    """One part of a template in a flat list, for an editor that shows the parts and edits the list."""

    kind: PieceKind
    text: str = ""  # the literal text without escapes (a separator's character), or the token's name
    padding: int = 0


def pieces(template: Template) -> list[Piece]:
    """The template's parts in order, a group as its `OPEN` piece, its parts and its `CLOSE` piece. A template with
    syntax problems loses what was wrong (a broken token, an unmatched bracket): edit only a template without."""
    found: list[Piece] = []

    def walk(nodes: tuple[_Node, ...]) -> None:
        for node in nodes:
            if isinstance(node, str):
                if separators_in(node):
                    found.extend(Piece(PieceKind.CHIP, char) for char in node)
                else:
                    found.append(Piece(PieceKind.TEXT, node))
            elif isinstance(node, _Group):
                found.append(Piece(PieceKind.OPEN))
                walk(node.nodes)
                found.append(Piece(PieceKind.CLOSE))
            else:
                found.append(Piece(PieceKind.TOKEN, node.name, node.padding))

    walk(template.nodes)
    return found


_SPECIAL = re.compile(r"([\\{}\[\]])")


def write(parts: Sequence[Piece]) -> str:
    """The template text of `parts`, the inverse of `parse` then `pieces`; text is escaped where it holds a brace, a
    bracket or a backslash."""
    out = []
    for part in parts:
        if part.kind in (PieceKind.TEXT, PieceKind.CHIP):
            out.append(_SPECIAL.sub(r"\\\1", part.text))
        elif part.kind is PieceKind.TOKEN:
            out.append(f"{{{part.text}:{'0' * part.padding}}}" if part.padding else f"{{{part.text}}}")
        else:
            out.append("[" if part.kind is PieceKind.OPEN else "]")
    return "".join(out)


def _read_field(inner: str, start: int, end: int, problems: list[Problem]) -> _Field:
    name, colon, spec = inner.partition(":")
    name, spec = name.strip().lower(), spec.strip()
    if not name:
        problems.append(Problem(ProblemKind.EMPTY_TOKEN, start, end))
    elif colon and set(spec) != {"0"}:
        problems.append(Problem(ProblemKind.BAD_FORMAT, start, end, spec))
    else:
        return _Field(name, len(spec), start, end)
    return _Field("", 0, start, end)


def _render(
    nodes: tuple[_Node, ...],
    context: NamingContext,
    active: tuple[str, ...],
    problems: list[Problem],
    span: tuple[int, int] | None,
) -> tuple[list[_Atom], bool]:
    """The pieces' text, and whether every token directly in `nodes` had a value.

    `active` lists the composite tokens being expanded, to catch cycles. `span` is the field of the
    previewed template that started the expansion: problems found inside a composite are reported there.
    """
    parts: list[_Atom] = []
    complete = True
    for node in nodes:
        if isinstance(node, str):
            if separators_in(node):
                parts.extend((char, *SEPARATORS[char]) for char in node)
            else:
                parts.append((node.replace(" ", _GAP), False, False))
        elif isinstance(node, _Group):
            inner, filled = _render(node.nodes, context, active, problems, span)
            parts.extend(inner if filled else [_NOTHING])
        else:
            value = _read(node, context, active, problems, span or (node.start, node.end))
            if value is None or value == "":
                complete = False
                parts.append(_NOTHING)
            elif node.padding and isinstance(value, int):
                parts.append((f"{value:0{node.padding}d}", True, True))
            else:
                parts.append((str(value), True, True))
    return parts, complete


def _assemble(atoms: list[_Atom]) -> str:
    """The pieces side by side, a join stand-in between each two that both ask for one. A pair of brackets with only
    left-out pieces inside is dropped."""
    kept: list[_Atom] = []
    for atom in atoms:
        opener = _CLOSERS.get(atom[0]) if atom[1:] == SEPARATORS.get(atom[0]) else None
        if opener:
            at = len(kept)
            while at and kept[at - 1] == _NOTHING:
                at -= 1
            if at < len(kept) and at and kept[at - 1] == (opener, *SEPARATORS[opener]):
                del kept[at - 1 :]
                continue
        kept.append(atom)
    out: list[str] = []
    joins = False
    for text, before, after in kept:
        if text == "":
            continue
        if out and joins and before:
            out.append(_GAP)
        out.append(text)
        joins = after
    return "".join(out)


def _read(
    field: _Field, context: NamingContext, active: tuple[str, ...], problems: list[Problem], where: tuple[int, int]
) -> str | int | None:
    if not field.name:
        return None  # already reported by the parser

    def report(kind: ProblemKind, detail: str = "") -> None:
        problems.append(Problem(kind, *where, detail))

    name = field.name
    defined = next((token for token in context.custom if token.name == name), None)
    builtin = TOKENS.get(name)
    if builtin:
        if builtin.track_templates_only and context.file_title is None:
            report(ProblemKind.NOT_HERE, name)
            return None
        if defined:
            report(ProblemKind.SHADOWS_BUILTIN, name)
        if field.padding and not builtin.numeric:
            report(ProblemKind.BAD_FORMAT, "0" * field.padding)
        value = builtin.read(context)
        spaced = builtin.joined
    elif defined:
        if field.padding:
            report(ProblemKind.BAD_FORMAT, "0" * field.padding)
        value = _read_defined(defined, context, active, problems, where)
        # A constant is typed text and a composite's own values were changed where they were read.
        spaced = defined.kind is CustomKind.PATTERN
    else:
        report(ProblemKind.UNKNOWN_TOKEN, name)
        return None
    mapped = context.value_maps.get(name)
    # The map matches the value as read and writes the text the user typed, so the join choice touches neither.
    if mapped and value not in (None, "") and str(value) in mapped:
        return mapped[str(value)]
    if spaced and isinstance(value, str):
        return value.replace(" ", context.space.character)
    return value


def _read_defined(
    token: CustomToken, context: NamingContext, active: tuple[str, ...], problems: list[Problem], where: tuple[int, int]
) -> str | None:
    def report(kind: ProblemKind, detail: str = "") -> None:
        problems.append(Problem(kind, *where, detail))

    if token.kind is CustomKind.CONSTANT:
        return token.text
    if token.kind is CustomKind.COMPOSITE:
        if token.name in active:
            report(ProblemKind.CYCLE, " > ".join((*active, token.name)))
            return None
        inner = parse(token.text)
        problems.extend(Problem(p.kind, *where, p.detail) for p in inner.problems)
        atoms, _ = _render(inner.nodes, context, (*active, token.name), problems, where)
        return _tidy(_assemble(atoms), context)
    try:
        regex = re.compile(token.text)
    except re.error as error:
        report(ProblemKind.BAD_PATTERN, str(error))
        return None
    if regex.groups < 1:
        report(ProblemKind.PATTERN_WITHOUT_GROUP)
        return None
    found = regex.search(_source_text(token.source, context))
    return found.group(1) if found else None


_FOLDER_LEVEL = {PatternSource.FOLDER_1: 1, PatternSource.FOLDER_2: 2, PatternSource.FOLDER_3: 3}


def _source_text(source: PatternSource, context: NamingContext) -> str:
    path = context.item.file.path
    if source is PatternSource.FILE_NAME:
        return path.stem
    parents = path.parents
    level = _FOLDER_LEVEL[source]
    return parents[level - 1].name if len(parents) >= level else ""
