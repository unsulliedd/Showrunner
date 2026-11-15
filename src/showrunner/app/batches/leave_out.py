"""What the next run leaves out: groups of planned change per batch, and files.

A left-out group is planned as if its options asked for nothing (`groups.without`), so it belongs to the batch whose
options it empties. A left-out file is one set of paths for the whole window, so a file left out in its season is
left out in its whole show and in a selection too, and the library marks it once. Both last for the session: they
choose a run, while the choices themselves stay in the working copy.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from showrunner.app.batches.batch import BatchKey
from showrunner.app.jobs.groups import ChangeGroup


@dataclass
class LeftOut:
    groups: dict[BatchKey, frozenset[ChangeGroup]] = field(default_factory=dict)
    files: set[Path] = field(default_factory=set)

    def groups_of(self, key: BatchKey) -> frozenset[ChangeGroup]:
        return self.groups.get(key, frozenset())

    def set_group(self, key: BatchKey, group: ChangeGroup, out: bool) -> None:
        groups = self.groups_of(key) | {group} if out else self.groups_of(key) - {group}
        if groups:
            self.groups[key] = groups
        else:
            self.groups.pop(key, None)

    def set_files(self, paths: Iterable[Path], out: bool) -> None:
        if out:
            self.files.update(paths)
        else:
            self.files.difference_update(paths)
