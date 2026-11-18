"""`mkvmerge --list-languages`: the language codes MKVToolNix accepts, with their names.

The list has no regions or scripts (MKVToolNix has no option that lists them), so those stay with the app's own lists.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from showrunner.tools.process import run

# The table has a heading and a rule under it before the first language.
_HEADING_LINES = 2


@dataclass(frozen=True, slots=True)
class MkvLanguage:
    name: str
    code3: str  # ISO 639-3, but the bibliographic form where ISO 639-2 has two (`dut`, `ger`)
    code2: str  # ISO 639-2; empty for a language without one
    code1: str  # ISO 639-1; empty for a language without one

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(c for c in (self.code3, self.code2, self.code1) if c))


class ListLanguagesError(Exception):
    """mkvmerge did not give a list of languages."""


def parse_languages(output: str) -> tuple[MkvLanguage, ...]:
    """The rows of the table; a line that is not one is skipped."""
    rows = []
    for line in output.splitlines()[_HEADING_LINES:]:
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) == 4 and cells[1]:
            rows.append(MkvLanguage(*cells))
    return tuple(rows)


def list_languages(mkvmerge: Path, *, timeout: float, cancel: threading.Event | None = None) -> tuple[MkvLanguage, ...]:
    """Every language mkvmerge knows. Raises `ListLanguagesError` when it gives no list."""
    result = run([mkvmerge, "--ui-language", "en", "--list-languages"], timeout=timeout, cancel=cancel)
    rows = parse_languages(result.stdout) if result.returncode == 0 else ()
    if not rows:
        raise ListLanguagesError(result.stderr.strip() or f"no list of languages (exit code {result.returncode})")
    return rows
