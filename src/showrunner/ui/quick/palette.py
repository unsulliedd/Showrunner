"""The command palette (Ctrl+K): what it can find and how a query ranks it. Pure; the window controller gathers the
entries and runs the one picked."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# What a result is; each kind has its icon in the palette.
KINDS: tuple[str, ...] = ("action", "file", "track", "token")
LIMIT = 12  # results shown at most; a longer list is narrowed by typing


@dataclass(frozen=True, slots=True)
class Entry:
    kind: str
    key: str  # what running it needs: an action's name, a file's path, a column's index, a token's name
    label: str
    detail: str = ""
    enabled: bool = True


def _rank(query: str, entry: Entry) -> int | None:
    """Lower ranks first; None when the entry does not match. Every word of the query must appear in the label or
    the detail. A label that starts with the query ranks first, then one where every word starts a word of the label,
    then one that holds the query inside a word."""
    label, detail = entry.label.casefold(), entry.detail.casefold()
    words = query.casefold().split()
    if not all(word in label or word in detail for word in words):
        return None
    whole = " ".join(words)
    if label.startswith(whole):
        return 0
    starts = re.split(r"[\W_]+", label)
    if all(any(start.startswith(word) for start in starts) for word in words):
        return 1
    if whole in label:
        return 2
    return 3 if all(word in label for word in words) else 4


def search(query: str, entries: Iterable[Entry], limit: int = LIMIT) -> list[Entry]:
    """The entries that match `query`, best first, in their given order within a rank. An empty query lists the
    actions, so the palette is also a menu."""
    entries = [e for e in entries if e.enabled]
    if not query.strip():
        return [e for e in entries if e.kind == "action"][:limit]
    ranked = [(rank, i, e) for i, e in enumerate(entries) if (rank := _rank(query, e)) is not None]
    return [e for _rank_, _i, e in sorted(ranked, key=lambda r: (r[0], r[1]))][:limit]
