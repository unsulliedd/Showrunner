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


class Output(StrEnum):
    """Where finished subtitles go. Beside the video, the subtitle stage writes the file itself and the video is not
    remuxed for it; a subtitle with no file of its own (a translation, a cleaned embedded track) is named by its
    language there."""

    VIDEO = ""  # into the new file, through the mux stage
    REPLACE = "replace"  # in place of the paired file, which goes to the Recycle Bin once the new one is checked
    NEW_FILE = "new-file"  # beside the paired file, named with `new_file_text`; the paired file stays


class Translate(StrEnum):
    """Which wanted languages are translated from the reference."""

    WHEN_MISSING = ""  # the ones no subtitle of the file has
    # Every one, whatever subtitles the file has, which stay as they are: the translation is written beside the video
    # named with `ai_file_text`, or goes into it as an extra track named `ai_track_name`.
    ALWAYS = "always"


@REGISTRY.register("subtitles")
@dataclass(frozen=True, slots=True)
class SubtitlesOptions:
    # IETF tag -> wanted or not. A wanted language no subtitle of a file has is translated from the reference; an
    # embedded text track in a wanted language is cleaned.
    languages: dict[str, Wanted] = field(default_factory=dict)
    translate: Translate = Translate.WHEN_MISSING
    reference: Reference = field(default_factory=Reference)
    # Rule set name -> used or paused. The used sets clean every finished subtitle.
    cleanup: dict[str, RuleSetUse] = field(default_factory=dict)
    # Syncs each paired subtitle file the Tracks tab adds; as it is, they are muxed with their own timing.
    sync: SyncEngine = SyncEngine.AS_IT_IS
    # `<engine>.<setting>` -> the value as typed, for that engine's adapter; empty is the engine's default. Kept per
    # engine, so a place that switches engines receives the settings set above for the one it switches to. Planned
    # into the sync step, which hands them to the adapter and judges its outcome by the two thresholds among them.
    sync_settings: dict[str, str] = field(default_factory=dict)
    lines: Lines = Lines.AS_THEY_ARE
    # The model that translates and re-splits; empty for the one chosen in Settings. Planned into those steps; no
    # engine re-splits yet.
    model: str = ""
    approval: Approval = Approval.NONE
    output: Output = Output.VIDEO
    # Put before the language code of a paired file's name for `Output.NEW_FILE`, so a scan still reads the language:
    # `Show.S01E01.tr.srt` becomes `Show.S01E01_cleaned.tr.srt`. Set in Settings, like the remux suffix.
    new_file_text: str = "_cleaned"
    # For `Translate.ALWAYS`: put before the language code of a translation written beside the video
    # (`Show.S01E01_ai.tr.srt`), so it never takes an existing file's name, and the name of the track it becomes in the
    # video, so players tell it from the subtitle already there. Set in Settings.
    ai_file_text: str = "_ai"
    ai_track_name: str = "AI translation"

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
# Characters Windows does not allow in a file name, the path separators among them.
_FORBIDDEN = set('<>:"/\\|?*')


def bad_new_file_text(text: str) -> bool:
    """Whether the new-file text cannot go into a file name: empty, or holding a path separator or another character a
    file name cannot hold. Empty would give the new file the name of the one it is made of."""
    return not text.strip() or any(ch in _FORBIDDEN or ord(ch) < 32 for ch in text)


def text_problem(options: SubtitlesOptions) -> bool:
    """Whether the options choose new files with a text that cannot name them. Not checked otherwise, since nothing
    reads the text then."""
    return options.output is Output.NEW_FILE and bad_new_file_text(options.new_file_text)


def ai_text_problem(options: SubtitlesOptions) -> bool:
    """Whether the options write translations beside the video named with a text that cannot name them."""
    beside = options.output is not Output.VIDEO
    return beside and options.translate is Translate.ALWAYS and bad_new_file_text(options.ai_file_text)


def ai_name_problem(options: SubtitlesOptions) -> bool:
    """Whether the options put translations into the video under an empty track name, which would not tell them from
    the subtitle already there."""
    into = options.output is Output.VIDEO
    return into and options.translate is Translate.ALWAYS and not options.ai_track_name.strip()
