"""One timed subtitle line."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Cue:
    start: float  # seconds
    end: float
    text: str

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2
