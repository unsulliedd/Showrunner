"""Checking the user's token definitions, for the editor that lists them."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.naming.custom import CustomKind, CustomToken
from showrunner.core.naming.template import Problem, ProblemKind, preview
from showrunner.core.naming.tokens import TOKENS, NamingContext

_NAME = re.compile(r"[a-z_][a-z0-9_]*")

# An empty file: checking a template only needs its structure, not the values.
_NO_FILE = MediaItem(Movie(""), MediaFile(Path("file.mkv"), ""))


class Part(StrEnum):
    NAME = "name"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class TokenProblem:
    """A problem in the definition called `name`; the positions are in its name or its text."""

    name: str
    part: Part
    problem: Problem


def check_tokens(
    custom: Sequence[CustomToken], value_maps: Mapping[str, Mapping[str, str]] | None = None
) -> list[TokenProblem]:
    """Every problem in the definitions and in the value maps' token names; empty when all is well."""
    context = NamingContext(_NO_FILE, custom=tuple(custom))
    found: list[TokenProblem] = []
    seen: set[str] = set()

    for token in custom:

        def add(part: Part, kind: ProblemKind, start: int, end: int, detail: str = "", name: str = token.name) -> None:
            found.append(TokenProblem(name, part, Problem(kind, start, end, detail)))

        if not _NAME.fullmatch(token.name):
            add(Part.NAME, ProblemKind.INVALID_NAME, 0, len(token.name))
        elif token.name in TOKENS:
            add(Part.NAME, ProblemKind.SHADOWS_BUILTIN, 0, len(token.name), token.name)
        elif token.name in seen:
            add(Part.NAME, ProblemKind.DUPLICATE_NAME, 0, len(token.name), token.name)
        seen.add(token.name)

        if token.kind is CustomKind.COMPOSITE:
            for problem in preview(token.text, context).problems:
                found.append(TokenProblem(token.name, Part.TEXT, problem))
        elif token.kind is CustomKind.PATTERN:
            try:
                groups = re.compile(token.text).groups
            except re.error as error:
                add(Part.TEXT, ProblemKind.BAD_PATTERN, error.pos or 0, len(token.text), str(error))
            else:
                if groups < 1:
                    add(Part.TEXT, ProblemKind.PATTERN_WITHOUT_GROUP, 0, len(token.text))

    for name in value_maps or {}:
        if name not in TOKENS and name not in seen:
            found.append(TokenProblem(name, Part.NAME, Problem(ProblemKind.UNKNOWN_TOKEN, 0, len(name), name)))
    return found
