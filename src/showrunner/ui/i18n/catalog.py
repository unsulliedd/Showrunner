"""String lookup by dotted key, with fallback to English and then to the key itself."""

from __future__ import annotations

import json
import logging
from pathlib import Path

FALLBACK_LANGUAGE = "en"
STRINGS_DIR = Path(__file__).parent / "strings"

_log = logging.getLogger(__name__)


class StringCatalog:
    """The strings of one active language. Catalog files are flat JSON objects of key to template."""

    def __init__(self, folder: Path, language: str = FALLBACK_LANGUAGE) -> None:
        self._folder = folder
        self._loaded: dict[str, dict[str, str]] = {}
        self._reported: set[str] = set()
        self.language = FALLBACK_LANGUAGE
        self.set_language(language)

    def set_language(self, language: str) -> None:
        if not (self._folder / f"{language}.json").is_file():
            _log.warning("No string catalog for language %r; using %r", language, FALLBACK_LANGUAGE)
            language = FALLBACK_LANGUAGE
        self.language = language

    def text(self, key: str, **values: object) -> str:
        """The template for `key` with `{name}` placeholders filled from `values`."""
        template = self._strings(self.language).get(key)
        if template is None:
            self._report(key, f"missing in {self.language!r}")
            template = self._strings(FALLBACK_LANGUAGE).get(key, key)
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            self._report(key, "placeholders do not match the values given")
            return template

    def _strings(self, language: str) -> dict[str, str]:
        if language not in self._loaded:
            self._loaded[language] = self._read(self._folder / f"{language}.json")
        return self._loaded[language]

    def _report(self, key: str, problem: str) -> None:
        # A missing key is looked up on every redraw of the view that uses it; one line in the log is enough.
        if key not in self._reported:
            self._reported.add(key)
            _log.warning("String %r: %s", key, problem)

    @staticmethod
    def _read(path: Path) -> dict[str, str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            _log.warning("String catalog %s is unreadable", path)
            return {}
        if not isinstance(data, dict):
            _log.warning("String catalog %s is not a JSON object", path)
            return {}
        return {k: v for k, v in data.items() if isinstance(v, str)}


_catalog = StringCatalog(STRINGS_DIR)


def set_language(language: str) -> None:
    _catalog.set_language(language)


def tr(key: str, **values: object) -> str:
    """The UI text for `key` in the active language. Every piece of UI text comes through this function."""
    return _catalog.text(key, **values)


def tr_plural(key: str, count: int, **values: object) -> str:
    """The text for `key.one` when `count` is 1 and `key.other` otherwise, with `{count}` filled in."""
    return _catalog.text(f"{key}.{'one' if count == 1 else 'other'}", count=count, **values)
