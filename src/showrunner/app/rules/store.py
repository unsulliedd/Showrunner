"""The user's cleanup rule sets in the data folder: read, written and handed out as one `RuleBook`."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from showrunner.app.storage.files import write_text_atomic
from showrunner.app.storage.paths import rules_dir
from showrunner.tools.cleanit import (
    PAUSES,
    Cache,
    RuleBook,
    RuleSet,
    dump_pauses,
    dump_set,
    file_name,
    load_book,
    signature,
    valid_name,
)


class RuleStore:
    """The rule sets as they are on disk. Each own set is the file `cleanit-<set>.yml` in the rules folder, written
    whole on every change; the pauses of built-in rules are the file `cleanit-pauses.yml`. A file edited by hand is
    read when its size or time changes. The folder is asked for at each use, so it follows the data folder."""

    def __init__(self, folder: Callable[[], Path] = rules_dir) -> None:
        self._folder = folder
        self._lock = threading.Lock()
        self._book: RuleBook | None = None
        self._read: Cache = {}  # what each file read as, so a long set is checked once
        self._seen: tuple[Path, tuple[tuple[str, int, int], ...]] | None = None
        self.revision = 0  # counts the times the rules were read again after they changed

    @property
    def folder(self) -> Path:
        return self._folder()

    def book(self) -> RuleBook:
        with self._lock:
            folder = self._folder()
            seen = (folder, signature(folder))
            if self._book is None or seen != self._seen:
                self._book, self._seen = load_book(folder, self._read), seen
                self.revision += 1
            return self._book

    def save(self, rule_set: RuleSet) -> None:
        """Write an own set. Raises ValueError for a name an own set cannot have."""
        if rule_set.builtin or (problem := valid_name(rule_set.name)):
            raise ValueError(problem if not rule_set.builtin else "built-in")
        write_text_atomic(self.folder / file_name(rule_set.name), dump_set(replace(rule_set, builtin=False)))

    def delete(self, name: str) -> None:
        """Remove an own set's file."""
        if not valid_name(name):  # a built-in name, and the pauses file, are never an own set's
            (self.folder / file_name(name)).unlink(missing_ok=True)

    def pause_builtin(self, rule: str, paused: bool) -> None:
        """Pause or unpause one rule of a built-in set, by its name."""
        names = {r.name for s in self.book().sets.values() if s.builtin for r in s.rules if r.paused} - {rule}
        names |= {rule} if paused else set()
        path = self.folder / file_name(PAUSES)
        if names:
            write_text_atomic(path, dump_pauses(frozenset(names)))
        else:
            path.unlink(missing_ok=True)
