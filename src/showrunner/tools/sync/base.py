"""What every sync engine shares: the request it is given, the outcome it reports and the settings it declares.

An engine's adapter moves a subtitle onto the timing of a reference (another subtitle, or the video's audio) and says
how far it moved it and how sure it is. Deciding what to do with the answer (keep the file as it is when it already
was in sync, mark it for review when the engine was unsure) belongs to the subtitle stage, so every engine gets the
same treatment.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from showrunner.core.language import Language

# The two settings every engine has: the largest shift (in seconds) at which a subtitle still counts as in sync, and
# the score below which the result is marked for review.
IN_SYNC_BELOW = "in_sync_below"
UNSURE_BELOW = "unsure_below"


class SettingKind(StrEnum):
    NUMBER = "number"  # a decimal number as typed
    CHOICE = "choice"  # one of `choices`; empty is the engine's own default


@dataclass(frozen=True, slots=True)
class Setting:
    """One setting of an engine, kept on a place as text under `<engine>.<key>`; empty is the engine's default."""

    key: str
    kind: SettingKind
    default: str  # what the engine does when the setting is empty, shown as the field's placeholder
    choices: tuple[str, ...] = ()  # CHOICE: the values besides the default


@dataclass(frozen=True, slots=True)
class SyncRequest:
    subtitle: Path  # the subtitle to move
    video: Path
    reference: Path | None  # a subtitle in time with the video; None: the video's audio
    output: Path  # where the moved subtitle is written, in the format of its extension
    settings: Mapping[str, str]  # the engine's own settings as set, without the engine's prefix
    language: Language | None  # of the subtitle, which decides the code page of a file with no byte order mark
    # Takes the fraction done, from 0 to 1, for an engine that can tell.
    progress: Callable[[float], None] | None = None
    cancel: threading.Event | None = None


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """What the engine found. `output` was written whether or not the subtitle needed moving."""

    offset: float  # seconds the subtitle was moved by; negative is earlier
    scale: float = 1.0  # the factor the times were stretched by first (a frame rate change); 1 is none
    # How well the moved subtitle agrees with the reference: the share of the subtitle's length that agrees, less the
    # share that does not, so 1 at best and below 0 where it disagrees. Comparable between files, not between engines.
    score: float = 1.0
    unsure: bool = False  # the engine itself doubts the result, whatever the score
    length: float = 0.0  # seconds from the start of the file to the end of the subtitle's last line

    @property
    def shift(self) -> float:
        """The largest distance in seconds that any line of the subtitle was moved: the offset, and the stretch added
        to it at the far end of the file."""
        return max(abs(self.offset), abs(self.offset + (self.scale - 1.0) * self.length))


class SyncError(Exception):
    """The engine could not sync the subtitle; the message says why."""


class SyncAdapter(Protocol):
    """One sync engine behind its program or library. Run on a background thread; Cancel stops it by `request.cancel`
    and raises `ProcessCancelledError`."""

    name: ClassVar[str]  # the engine's value in the options, which prefixes its settings
    audio: bool  # can work against the video's audio, needing no reference subtitle (its program is found)
    # The engine's own settings; the two common ones (`IN_SYNC_BELOW`, `UNSURE_BELOW`) follow in `defaults`.
    settings: ClassVar[tuple[Setting, ...]]
    # What the common settings are when a place sets none, as text.
    defaults: ClassVar[Mapping[str, str]]

    def sync(self, request: SyncRequest) -> SyncOutcome: ...
