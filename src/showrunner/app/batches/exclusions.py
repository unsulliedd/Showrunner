"""Which places are excluded from every run, a value per place that the nearest place decides.

A place holds `True` (excluded), `False` (included again, inside an excluded place) or nothing, in which case it takes
the value of its parent; the top of a tree is included. So excluding a show excludes every season and episode in it,
and a season or episode set to `False` is in again with what lies inside it. A value equal to what its place receives
is not kept, so a place that follows its parent leaves no entry behind and a later change above still reaches it.
Unlike choices, exclusion is no part of a profile or its working copy: Discard, Revert and Save leave it alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from showrunner.app.batches.batch import BatchKey


@dataclass
class Exclusions:
    values: dict[BatchKey, bool] = field(default_factory=dict)

    def excluded(self, key: BatchKey) -> bool:
        """Whether the place is out of every run: its own value, else the nearest parent's, else included."""
        place: BatchKey | None = key
        while place is not None:
            if place in self.values:
                return self.values[place]
            place = place.parent
        return False

    def received(self, key: BatchKey) -> bool:
        """The value the place gets from above; included for a show and for the Movies group."""
        return self.excluded(key.parent) if key.parent is not None else False

    def own(self, key: BatchKey) -> bool | None:
        """The value the place holds itself; None when it follows its parent."""
        return self.values.get(key)

    def set(self, key: BatchKey, excluded: bool) -> None:
        """Give the place a value. Where it is what the place receives, it follows its parent instead. Places inside
        whose own value now equals what they receive are dropped too, so excluding a show again excludes a season
        that was included on its own before the show was included."""
        if excluded == self.received(key):
            self.values.pop(key, None)
        else:
            self.values[key] = excluded
        for place in [p for p in self.values if p != key and p.within(key)]:
            if self.values[place] == self.received(place):
                del self.values[place]
