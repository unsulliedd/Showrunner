"""What cleaning does to a subtitle file, read from the file as it is now: the counts the Cleanup row shows, the marked
lines of the Lines panel and the live test of the rule editor."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from showrunner.core.cue import read_cues
from showrunner.core.language import Language
from showrunner.tools.cleanit import CueResult, RuleBook, clean_cues


@dataclass(frozen=True, slots=True)
class Effect:
    results: tuple[CueResult, ...]

    @property
    def dropped(self) -> int:
        return sum(r.dropped for r in self.results)

    @property
    def changed(self) -> int:
        return sum(r.changed for r in self.results)

    @property
    def looped(self) -> int:
        return sum(r.looped for r in self.results)


def file_effect(source: Path, language: Language | None, names: Sequence[str], book: RuleBook) -> Effect | None:
    """The effect of the sets `names` on the cues of `source`, or None for a file that cannot be read."""
    try:
        cues = read_cues(source, language)
        compiled = book.compile(names, language)
    except (OSError, ValueError):  # a file that is no subtitle, or a rule that cannot be built
        return None
    return Effect(tuple(clean_cues(cues, compiled)))
