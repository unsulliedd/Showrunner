"""What this run alone leaves out: groups of planned change, and files, each a value per place that the nearest place
decides. Review shows them as unticked boxes.

A left-out group is planned as if its options asked for nothing (`groups.without`). Leaving it out of a season leaves
it out of every episode of the season, and an episode can put it back for itself, as with exclusion (`Exclusions`,
whose rules both follow: a value equal to what the place receives is not kept). A file left out is the same, set on
the file's own place. Both last until the place is applied: they choose one run, while the choices stay in the
working copy and the saved exclusion of a place is a different thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from showrunner.app.batches.batch import BatchKey
from showrunner.app.batches.exclusions import Exclusions
from showrunner.app.jobs.groups import ChangeGroup


@dataclass
class LeftOut:
    groups: dict[ChangeGroup, Exclusions] = field(default_factory=dict)  # per group, which places leave it out
    files: Exclusions = field(default_factory=Exclusions)  # which places this run leaves out

    def groups_of(self, key: BatchKey) -> frozenset[ChangeGroup]:
        """The groups the place leaves out: its own value of each, else the nearest place's above it."""
        return frozenset(group for group, places in self.groups.items() if places.excluded(key))

    def set_group(self, key: BatchKey, group: ChangeGroup, out: bool) -> None:
        self.groups.setdefault(group, Exclusions()).set(key, out)

    def file_out(self, key: BatchKey) -> bool:
        return self.files.excluded(key)

    def set_file(self, key: BatchKey, out: bool) -> None:
        self.files.set(key, out)

    def clear(self, key: BatchKey) -> None:
        """Tick everything again for the place and what lies inside it, as after its Apply. A group a place above
        still leaves out is put back for this place with a value of its own, so the boxes read ticked here while the
        places beside it keep what they receive."""
        for places in (self.files, *self.groups.values()):
            for place in [p for p in places.values if p.within(key)]:
                del places.values[place]
            if places.excluded(key):
                places.set(key, False)

    @property
    def empty(self) -> bool:
        return not self.files.values and not any(places.values for places in self.groups.values())
