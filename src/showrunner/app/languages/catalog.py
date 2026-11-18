"""The language codes the app can write: babelfish's, plus the ones MKVToolNix adds when it is installed.

babelfish ships with the app, so the picker always has its list. `mkvmerge --list-languages` is read once per program
(a language list does not change while the app runs); its codes missing from babelfish (mostly ISO 639-5 collective
codes such as `roa`) join the list, and its set of codes is the final check of a typed tag, since mkvmerge refuses
a code it does not know only when the file is written.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from showrunner.core.language import Language, add_languages
from showrunner.tools.mkvtoolnix.languages import ListLanguagesError, MkvLanguage, list_languages
from showrunner.tools.process import ProcessError

_log = logging.getLogger(__name__)
_TIMEOUT = 30.0


class TagProblem(StrEnum):
    NONE = "none"
    NOT_A_TAG = "not-a-tag"  # not a language, or a region or script that does not exist
    UNKNOWN_TO_MKVTOOLNIX = "unknown-to-mkvtoolnix"  # a language the app knows but mkvmerge would refuse


@dataclass(frozen=True, slots=True)
class TagCheck:
    language: Language | None
    problem: TagProblem


def read_languages(mkvmerge: Path | None) -> tuple[MkvLanguage, ...] | None:
    """What MKVToolNix lists; None without it or when it gives no list. It touches nothing shared, so it may run on
    a pool thread; `use_languages` then takes the result on the thread that reads languages."""
    if mkvmerge is None:
        return None
    try:
        return list_languages(mkvmerge, timeout=_TIMEOUT)
    except (ListLanguagesError, ProcessError) as error:
        _log.warning("The list of MKVToolNix languages could not be read: %s", error)
        return None


def use_languages(rows: Sequence[MkvLanguage] | None) -> frozenset[str] | None:
    """Add the codes babelfish lacks to the app's languages (and drop those added before when there is no list), and
    return the codes MKVToolNix accepts in lower case; None when there is no list."""
    add_languages({} if rows is None else {row.code3.casefold(): row.name for row in rows})
    return None if rows is None else frozenset(code.casefold() for row in rows for code in row.codes)


def load_known_codes(mkvmerge: Path | None) -> frozenset[str] | None:
    """`read_languages` and `use_languages` in one step."""
    return use_languages(read_languages(mkvmerge))


def check_tag(text: str, known: frozenset[str] | None) -> TagCheck:
    """What a typed tag is: a language the app can write, or what is wrong with it. `known` is `load_known_codes`; with
    None only the app's own lists decide."""
    language = Language.parse(text)
    if language is None:
        return TagCheck(None, TagProblem.NOT_A_TAG)
    if known is not None and known.isdisjoint(language.codes):
        return TagCheck(language, TagProblem.UNKNOWN_TO_MKVTOOLNIX)
    return TagCheck(language, TagProblem.NONE)
