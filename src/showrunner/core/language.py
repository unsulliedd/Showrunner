"""Language value type and the lists behind the language picker; the only module that imports babelfish."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from babelfish import COUNTRY_MATRIX, LANGUAGE_MATRIX, SCRIPT_MATRIX
from babelfish import Language as _Babelfish
from babelfish.exceptions import Error as _BabelfishError

# Areas of the UN M.49 list that a tag uses as its region (`es-419`) and that babelfish's countries lack.
AREAS: dict[str, str] = {"419": "Latin America and the Caribbean"}

_LANGUAGE_CODES = {
    code: row for row in LANGUAGE_MATRIX for code in (row.alpha3, row.alpha3b, row.alpha3t, row.alpha2) if code
}
_REGION_NAMES = {row.alpha2: row.name for row in COUNTRY_MATRIX} | AREAS
_SCRIPT_NAMES = {row.code: row.name for row in SCRIPT_MATRIX}
_SMALL_WORDS = {"and", "of", "the", "da", "de"}
# Variant, extension and private-use subtags are kept as typed; each is 1 to 8 letters or digits.
_SUBTAG = re.compile(r"[A-Za-z0-9]{1,8}")
_VARIANT = re.compile(r"[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}")

# Codes of languages babelfish lacks (mostly ISO 639-5 collective codes) and their names, given by the app when a
# program that lists them is installed. A code finds them, never a name, so a word of a file name is no language.
_extra: dict[str, str] = {}
_given = 0  # how often `add_languages` ran


def add_languages(extra: Mapping[str, str]) -> None:
    """Make the codes of `extra` (code to English name) valid languages, in place of any given before."""
    global _given
    _extra.clear()
    _extra.update({code: name for code, name in extra.items() if code not in _LANGUAGE_CODES})
    _given += 1
    languages.cache_clear()
    _parse.cache_clear()


def languages_given() -> int:
    """How often the extra languages were given: what a code parses to may differ after each, so a result kept from
    parsing codes holds only while this stays the same."""
    return _given


@dataclass(frozen=True, slots=True)
class Language:
    """A language by identity: `tr` and `tur` give equal values.

    The region, script and the rest are part of the identity, so `pt-BR` differs from `pt`.
    """

    alpha3: str
    region: str | None = None  # ISO 3166 alpha-2 (`BR`) or an M.49 area (`419`)
    script: str | None = None  # ISO 15924 (`Latn`)
    rest: str = ""  # variants, extensions and private use as typed (`1996`, `x-foo`), after the region

    def __post_init__(self) -> None:
        if self.alpha3 not in _LANGUAGE_CODES and self.alpha3 not in _extra:
            raise ValueError(f"{self.alpha3!r} is not a valid language")
        if self.region is not None and self.region not in _REGION_NAMES:
            raise ValueError(f"{self.region!r} is not a valid region")
        if self.script is not None and self.script not in _SCRIPT_NAMES:
            raise ValueError(f"{self.script!r} is not a valid script")

    @property
    def _alpha2(self) -> str:
        row = _LANGUAGE_CODES.get(self.alpha3)
        return row.alpha2 if row else ""

    @property
    def codes(self) -> tuple[str, ...]:
        """Every code the language has, lower case: `por`, `pt`; the 3-letter ones may differ (`deu`, `ger`)."""
        row = _LANGUAGE_CODES.get(self.alpha3)
        found = (row.alpha3, row.alpha3b, row.alpha3t, row.alpha2) if row else (self.alpha3,)
        return tuple(dict.fromkeys(c for c in found if c))

    @property
    def ietf(self) -> str:
        """Shortest IETF tag: `tr`, `pt-BR`, `zh-Hant`, `es-419`; the 3-letter code when no 2-letter one exists."""
        return "-".join(p for p in (self._alpha2 or self.alpha3, self.script, self.region, self.rest) if p)

    @property
    def name(self) -> str:
        """English name of the language alone."""
        row = _LANGUAGE_CODES.get(self.alpha3)
        # A code the program that added it no longer lists is shown as its code.
        return _Babelfish(row.alpha3).name if row else _extra.get(self.alpha3, self.alpha3)

    @property
    def display(self) -> str:
        """English name with the script and region: `Portuguese (Brazil)`, `Serbian (Latin, Serbia)`."""
        parts = [_SCRIPT_NAMES[self.script]] if self.script else []
        parts += [region_name(self.region)] if self.region else []
        return f"{self.name} ({', '.join(parts)})" if parts else self.name

    @classmethod
    def parse(cls, text: str) -> Language | None:
        """Read an IETF tag (`pt-BR`, `es-419`, `sr-Latn-RS`), an ISO 639-2 code (either form) or an English name.

        Returns None for text that is not a language, for a tag whose region or script is unknown, and for `und`
        (undetermined).
        """
        return _parse(text.strip())


# Rules read the same few tags once per track and rule; a code added later must be seen, so `add_languages` clears it.
@lru_cache(maxsize=4096)
def _parse(text: str) -> Language | None:
    return _from_tag(text) or _from_name(text)


def _from_tag(text: str) -> Language | None:
    head, *subtags = text.split("-")
    code = head.casefold()
    row = _LANGUAGE_CODES.get(code)
    alpha3 = row.alpha3 if row else code if code in _extra else None
    if alpha3 is None or alpha3 == "und":
        return None
    script = region = None
    rest = subtags
    if rest and len(rest[0]) == 4 and rest[0].isalpha():
        script = rest[0].capitalize()
        rest = rest[1:]
        if script not in _SCRIPT_NAMES:
            return None
    if rest and ((len(rest[0]) == 2 and rest[0].isalpha()) or (len(rest[0]) == 3 and rest[0].isdigit())):
        region = rest[0].upper()
        rest = rest[1:]
        if region not in _REGION_NAMES:
            return None
    if rest and not (_VARIANT.fullmatch(rest[0]) or len(rest[0]) == 1):
        return None  # what follows is a variant or a singleton (`x`, `u`), not a leftover language or region
    if not all(_SUBTAG.fullmatch(s) for s in rest) or (rest and len(rest[-1]) == 1):
        return None  # a singleton (`x`) with nothing after it is no extension
    return Language(alpha3, region, script, "-".join(rest))


def _from_name(text: str) -> Language | None:
    try:
        found = _Babelfish.fromname(text)
    except (ValueError, _BabelfishError):
        return None
    return None if found.alpha3 == "und" else Language(found.alpha3)


def region_name(code: str) -> str:
    """`Brazil` for `BR`, `Latin America and the Caribbean` for `419`."""
    name = _REGION_NAMES[code]
    if code in AREAS:
        return name
    return " ".join(w if w.casefold() in _SMALL_WORDS else w.capitalize() for w in name.lower().split())


@dataclass(frozen=True, slots=True)
class ListedLanguage:
    """One line of the picker's list: the code a tag is built from, and the words a search finds it by."""

    code: str  # the 3-letter code (`por`)
    name: str
    codes: tuple[str, ...]  # every code of the language, lower case: `por`, `pt`
    common: bool  # has a 2-letter code


@lru_cache(maxsize=1)
def languages() -> tuple[ListedLanguage, ...]:
    """Every language the app knows, by name: babelfish's about 7,900 ISO 639-3 languages and the extra codes."""
    rows = [
        ListedLanguage(
            row.alpha3,
            _Babelfish(row.alpha3).name,
            Language(row.alpha3).codes,
            bool(row.alpha2),
        )
        for row in LANGUAGE_MATRIX
    ]
    rows += [ListedLanguage(code, name, (code,), False) for code, name in _extra.items()]
    return tuple(sorted(rows, key=lambda r: r.name.casefold()))


def regions() -> tuple[tuple[str, str], ...]:
    """Regions as (code, name) by name; the M.49 areas come with the countries."""
    return tuple(sorted(((code, region_name(code)) for code in _REGION_NAMES), key=lambda r: r[1].casefold()))


def scripts() -> tuple[tuple[str, str], ...]:
    """Scripts as (code, name) by name."""
    return tuple(sorted(_SCRIPT_NAMES.items(), key=lambda r: r[1].casefold()))
