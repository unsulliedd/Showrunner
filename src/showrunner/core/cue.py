"""One timed subtitle line."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Cue:
    # Not used by the app yet; the subtitle stage (sync, re-split, translate) works on cues.
    start: float  # seconds
    end: float
    text: str

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2
