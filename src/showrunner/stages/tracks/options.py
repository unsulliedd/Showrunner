"""Options of the tracks stage: an ordered list of rules, each with a match and an action.

Precedence: the first enabled rule whose verdict is `keep` or `drop` and whose match fits a track decides
whether the track stays. A rule with the verdict `pass` leaves that decision to the rules after it. A track
no rule decides on is kept. First-match-wins is used because a list then reads like a sentence ("keep
Turkish subtitles, drop every other subtitle"), and the rule that dropped a track is a single, definite
answer for the preview; with later rules overriding earlier ones, that answer would depend on the whole list.

Flag actions work on the tracks that are kept. See `FlagShape`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from showrunner.core.media import SubtitleFile
from showrunner.core.options.registry import REGISTRY


class KindTest(StrEnum):
    ANY = "any"
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


class FlagTest(StrEnum):
    ANY = "any"
    SET = "set"
    UNSET = "unset"


class SourceTest(StrEnum):
    """Where a track comes from: from inside the video file, or from a paired subtitle file beside it."""

    ANY = "any"
    EMBEDDED = "embedded"
    PAIRED = "paired"


class Verdict(StrEnum):
    PASS = "pass"  # no opinion on keeping: only the flag actions of the rule apply
    KEEP = "keep"
    DROP = "drop"


class FlagShape(StrEnum):
    """What a rule does to the default or the forced flag.

    `first`: among the kept tracks the rule matches, the first one of each kind gets the flag and every
    other kept track of that kind loses it. Rules are tried in order, and the first rule that matches a
    track of a kind decides that kind, so a later `first` rule acts as a fallback ("Turkish audio, else
    English audio"). A kind no `first` rule reaches keeps its flags as they are.
    """

    LEAVE = "leave"
    FIRST = "first"


@dataclass(frozen=True, slots=True)
class TrackMatch:
    """A track fits when every test that is set fits; a match with nothing set fits every track."""

    kind: KindTest = KindTest.ANY
    # ISO 639 codes or IETF tags ("tr", "tur", "pt-BR"); the track fits when it has any of them. A tag
    # without a region or script fits every region and script of that language. `und` fits a track that
    # has no language. An entry that is not a language fits nothing.
    languages: list[str] = field(default_factory=list)
    # Matroska codec IDs (`A_AAC`) or display names (`AAC`, `Dolby Digital Plus`), any case; the track fits
    # when it has any of them.
    codecs: list[str] = field(default_factory=list)
    # Audio channels, both ends included; 0 leaves that end open. Equal ends (both 6) are an exact count.
    # A track with unknown channels fits no channel test.
    min_channels: int = 0
    max_channels: int = 0
    default: FlagTest = FlagTest.ANY
    forced: FlagTest = FlagTest.ANY
    hearing_impaired: FlagTest = FlagTest.ANY
    visual_impaired: FlagTest = FlagTest.ANY
    commentary: FlagTest = FlagTest.ANY
    original: FlagTest = FlagTest.ANY
    # The track name: text found anywhere in it, or a regular expression searched in it. Any case. An
    # invalid expression fits nothing.
    name: str = ""
    name_is_regex: bool = False
    # Only a subtitle can come from a paired file, so `paired` fits no audio or video track.
    source: SourceTest = SourceTest.ANY


@dataclass(frozen=True, slots=True)
class TrackRule:
    enabled: bool = True
    # Shown in the preview next to what the rule did; it has no effect on matching.
    label: str = ""
    match: TrackMatch = field(default_factory=TrackMatch)
    verdict: Verdict = Verdict.PASS
    default: FlagShape = FlagShape.LEAVE
    forced: FlagShape = FlagShape.LEAVE
    # Written by a choice made directly on a track (a chip, a card or a column of the track matrix) rather than by
    # hand. It matches like any other rule; the mark tells the views which rule a choice owns.
    from_choice: bool = False


@dataclass(frozen=True, slots=True)
class PairedFile:
    """Which paired subtitle files go into the video: the files of a language and format, with the forced and
    hearing impaired marks their names carry, so `tr.srt` and `tr.forced.srt` are chosen apart."""

    language: str = "und"  # IETF tag, `und` for a file without one
    format: str = ""  # the file's extension without the dot, lower case: `srt`, `ass`, `sup`
    forced: bool = False
    sdh: bool = False

    @classmethod
    def of(cls, subtitle: SubtitleFile) -> PairedFile:
        language = subtitle.language.ietf if subtitle.language else "und"
        return cls(language, Path(subtitle.path).suffix.lower().lstrip("."), subtitle.forced, subtitle.sdh)


@REGISTRY.register("tracks")
@dataclass(frozen=True, slots=True)
class TracksOptions:
    # Without a switched-on rule, tracks stay as they are.
    rules: list[TrackRule] = field(default_factory=list)
    # The paired subtitle files added to the video; the rules then treat each like a track (drop it, flag it). A
    # file is added only when chosen here, never because a rule is on, so a profile without these remuxes nothing
    # for a paired file.
    add_paired: list[PairedFile] = field(default_factory=list)
    # Rules also see the commentary, hearing impaired and forced flags a track's name implies, since many
    # files name such tracks without setting the flag.
    flags_from_names: bool = True
