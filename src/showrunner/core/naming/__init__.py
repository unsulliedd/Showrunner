"""Naming: tokens read from a file, the template language, display names for codecs and HDR kinds."""

from showrunner.core.naming.check import Part, TokenProblem, check_tokens
from showrunner.core.naming.custom import CustomKind, CustomToken, PatternSource
from showrunner.core.naming.names import DEFAULT_CODEC_NAMES, DEFAULT_HDR_NAMES, guess_source, guess_source_of
from showrunner.core.naming.options import SUGGESTED_TEMPLATES, NamingOptions
from showrunner.core.naming.template import (
    Piece,
    PieceKind,
    Preview,
    Problem,
    ProblemKind,
    Template,
    parse,
    pieces,
    preview,
    write,
)
from showrunner.core.naming.tokens import TOKENS, NamingContext, Scope, Token

__all__ = [
    "DEFAULT_CODEC_NAMES",
    "DEFAULT_HDR_NAMES",
    "SUGGESTED_TEMPLATES",
    "TOKENS",
    "CustomKind",
    "CustomToken",
    "NamingContext",
    "NamingOptions",
    "Part",
    "PatternSource",
    "Piece",
    "PieceKind",
    "Preview",
    "Problem",
    "ProblemKind",
    "Scope",
    "Template",
    "Token",
    "TokenProblem",
    "check_tokens",
    "guess_source",
    "guess_source_of",
    "parse",
    "pieces",
    "preview",
    "write",
]
