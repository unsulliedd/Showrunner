"""The picker's language list: filtered by what was typed and put in the order the user most likely wants."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from showrunner.core.language import ListedLanguage


@dataclass(frozen=True, slots=True)
class LanguageIndex:
    """The languages with their search keys made once, so filtering about 8,000 of them on a key press stays quick."""

    rows: tuple[ListedLanguage, ...]
    names: tuple[str, ...]  # lower-cased, one per row

    @classmethod
    def of(cls, rows: Sequence[ListedLanguage]) -> LanguageIndex:
        return cls(tuple(rows), tuple(row.name.casefold() for row in rows))

    def search(self, query: str, batch: Collection[str] = ()) -> list[ListedLanguage]:
        """The languages that fit every word of `query` (in the name, or at the start of a code). The batch's
        languages (their 3-letter codes) come first, then the ones with a 2-letter code, then the rest; within each,
        an exact code first, then a name that starts with the query, then by name."""
        words = query.casefold().split()
        whole = query.strip().casefold()
        found: list[tuple[tuple[int, int], ListedLanguage]] = []
        for row, name in zip(self.rows, self.names, strict=True):
            if not all(w in name or any(code.startswith(w) for code in row.codes) for w in words):
                continue
            tier = 0 if row.code in batch else 1 if row.common else 2
            rank = 0 if whole in row.codes else 1 if name.startswith(whole) else 2
            found.append(((tier, rank), row))
        # `rows` is by name and the sort is stable, so each group stays by name.
        found.sort(key=lambda entry: entry[0])
        return [row for _, row in found]
