"""Options of the subtitle stage: what a place does with the subtitles of its files.

Every field asks for nothing when empty, so a profile without them plans no subtitle work. The fields keyed by item
(wanted languages, rule sets, engine settings) are laid over the ones received item by item, so a nearer place adds
a language or pauses a received rule set without replacing the whole list; their second value (`NOT_HERE`,
`PAUSED`, an empty setting) is how a nearer place cancels one item it receives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from showrunner.core.options.registry import REGISTRY
from showrunner.stages.tracks.options import TrackMatch


class Wanted(StrEnum):
    WANTED = "wanted"
    NOT_HERE = "not-here"  # a language received from above that this place does not want


class RuleSetUse(StrEnum):
    USED = "used"
    PAUSED = "paused"  # a set received from above, or the place's own, that cleans nothing here


class ReferenceKind(StrEnum):
    # Per file: the first text subtitle, else the first picture subtitle read by OCR, else the audio; tracks in the
    # preferred reference language first.
    AUTOMATIC = ""
    TRACK = "track"  # the first track of the chosen group, else Automatic for a file without one
    AUDIO = "audio"  # syncs against the sound; no text to translate from


@dataclass(frozen=True, slots=True)
class Reference:
    kind: ReferenceKind = ReferenceKind.AUTOMATIC
    track: TrackMatch = field(default_factory=TrackMatch)  # for `TRACK`: the group, as Tracks' chips match one


class SyncEngine(StrEnum):
    AS_IT_IS = ""
    FFSUBSYNC = "ffsubsync"
    ALASS = "alass"
    LAPSE = "lapse"


class Lines(StrEnum):
    AS_THEY_ARE = ""
    RESPLIT = "resplit"  # onto the reference's lines, after a sync


class Approval(StrEnum):
    NONE = ""  # finished subtitles are muxed at once
    TRANSLATIONS = "translations"  # a file with a translation waits for the user before its mux
    EVERY = "every"  # a file with any finished subtitle waits


@REGISTRY.register("subtitles")
@dataclass(frozen=True, slots=True)
class SubtitlesOptions:
    # IETF tag -> wanted or not. A wanted language no subtitle of a file has is translated from the reference; an
    # embedded text track in a wanted language is cleaned.
    languages: dict[str, Wanted] = field(default_factory=dict)
    reference: Reference = field(default_factory=Reference)
    # Rule set name -> used or paused. The used sets clean every finished subtitle.
    cleanup: dict[str, RuleSetUse] = field(default_factory=dict)
    # Syncs each paired subtitle file the Tracks tab adds; as it is, they are muxed with their own timing.
    sync: SyncEngine = SyncEngine.AS_IT_IS
    # `<engine>.<setting>` -> the value as typed, for that engine's adapter; empty is the engine's default. Kept per
    # engine, so a place that switches engines receives the settings set above for the one it switches to. Planned
    # into the sync step, but no adapter reads them yet and no view sets them.
    sync_settings: dict[str, str] = field(default_factory=dict)
    lines: Lines = Lines.AS_THEY_ARE
    # The model that translates and re-splits; empty for the one chosen in Settings. Planned into those steps, but
    # no engine reads it yet and no view sets it.
    model: str = ""
    approval: Approval = Approval.NONE

    def wanted(self) -> tuple[str, ...]:
        return tuple(tag for tag, value in self.languages.items() if value is Wanted.WANTED)

    def rule_sets(self) -> tuple[str, ...]:
        """The used sets, sorted, so the same choice made in another order plans the same work."""
        return tuple(sorted(name for name, use in self.cleanup.items() if use is RuleSetUse.USED))

    def engine_settings(self) -> tuple[tuple[str, str], ...]:
        """The chosen engine's own settings that are set, without the engine prefix."""
        prefix = f"{self.sync.value}."
        return tuple(
            sorted(
                (key.removeprefix(prefix), value)
                for key, value in self.sync_settings.items()
                if key.startswith(prefix) and value
            )
        )


# The fields laid over what a place receives item by item rather than replaced whole.
PER_ITEM_FIELDS = ("languages", "cleanup", "sync_settings")
