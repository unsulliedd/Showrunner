"""Template text to a parsed tree to a name.

Syntax: `{token}`, `{token:00}` (zero padding, numbers only), `[optional group]`, and a backslash before
any character to write it literally. A group is left out when a token directly inside it is empty.

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

# Parentheses left empty or padded by an empty token inside them.
_TIDY = (
    (re.compile(r"\(\s+"), "("),
    (re.compile(r"\s+\)"), ")"),
    (re.compile(r"\(\)"), ""),
    (re.compile(r"\s{2,}"), " "),
)


def _tidy(text: str) -> str:
    for pattern, replacement in _TIDY:
        text = pattern.sub(replacement, text)
    return text.strip()


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
        text, _ = _render(self.nodes, context, (), problems, None)
        return Preview(_tidy(text), tuple(sorted(problems, key=lambda p: p.start)))


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
    TOKEN = "token"
    OPEN = "open"  # the `[` of a group
    CLOSE = "close"  # its `]`


@dataclass(frozen=True, slots=True)
class Piece:
    """One part of a template in a flat list, for an editor that shows the parts and edits the list."""

    kind: PieceKind
    text: str = ""  # the literal text without escapes, or the token's name
    padding: int = 0


def pieces(template: Template) -> list[Piece]:
    """The template's parts in order, a group as its `OPEN` piece, its parts and its `CLOSE` piece. A template with
    syntax problems loses what was wrong (a broken token, an unmatched bracket): edit only a template without."""
    found: list[Piece] = []

    def walk(nodes: tuple[_Node, ...]) -> None:
        for node in nodes:
            if isinstance(node, str):
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
        if part.kind is PieceKind.TEXT:
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
) -> tuple[str, bool]:
    """The text, and whether every token directly in `nodes` had a value.

    `active` lists the composite tokens being expanded, to catch cycles. `span` is the field of the
    previewed template that started the expansion: problems found inside a composite are reported there.
    """
    parts: list[str] = []
    complete = True
    for node in nodes:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, _Group):
            text, filled = _render(node.nodes, context, active, problems, span)
            if filled:
                parts.append(text)
        else:
            value = _read(node, context, active, problems, span or (node.start, node.end))
            if value is None or value == "":
                complete = False
            elif node.padding and isinstance(value, int):
                parts.append(f"{value:0{node.padding}d}")
            else:
                parts.append(str(value))
    return "".join(parts), complete


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
        if defined:
            report(ProblemKind.SHADOWS_BUILTIN, name)
        if field.padding and not builtin.numeric:
            report(ProblemKind.BAD_FORMAT, "0" * field.padding)
        value = builtin.read(context)
        spaced = True
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
    # The map matches the value as read and writes the text the user typed, so the space choice touches neither.
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
        text, _ = _render(inner.nodes, context, (*active, token.name), problems, where)
        return _tidy(text)
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
