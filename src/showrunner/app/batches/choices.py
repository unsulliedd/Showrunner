"""Choices made directly on a track (keep, drop, default, forced) written as ordinary track rules, and the choice
to add a paired subtitle file.

A choice is made on a track signature, the group of alike tracks across a batch that one chip or matrix column
stands for. It becomes one rule marked `from_choice`, so what a chip shows is what the rules produce: there is no
second layer of choices the engine cannot see. Choice rules lead the rule list, because the first rule that decides
wins and a click on a chip has to take effect over a hand-written rule that says otherwise; the hand-written rule
itself is never edited.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from functools import lru_cache

from showrunner.core.media import MediaItem
from showrunner.core.track import Track, TrackKind, flags_with_name
from showrunner.stages.tracks import (
    NO_LANGUAGE,
    FlagShape,
    FlagTest,
    KindTest,
    PairedFile,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
    stand_in,
)


@dataclass(frozen=True, slots=True)
class TrackSignature:
    """What makes tracks alike across a batch: kind, language, codec, channels and what the track is (commentary,
    hearing impaired, forced, audio description), read as the rules read them. Default is not part of it, since a
    choice changes it. The name is not either, so tracks named after each episode are one group; only a group that
    `TrackGroups` tells apart by name carries it."""

    kind: TrackKind
    language: str  # IETF tag, `und` for a track without one
    codec: str  # Matroska codec ID
    channels: int | None  # audio only
    commentary: bool = False
    hearing_impaired: bool = False
    forced: bool = False
    visual_impaired: bool = False
    name: str | None = None  # None: the name does not matter; "" for an unnamed track of a group told apart by name

    @classmethod
    def of(cls, track: Track, flags_from_names: bool = True) -> TrackSignature:
        """The signature without the name; `TrackGroups.signature` adds it where a batch needs it."""
        return _nameless(track, flags_from_names)

    @classmethod
    def _read(cls, track: Track, flags_from_names: bool) -> TrackSignature:
        language = track.language.ietf if track.language else NO_LANGUAGE
        channels = track.audio.channels if track.audio else None
        flags = flags_with_name(track) if flags_from_names else track.flags
        return cls(
            track.kind,
            language,
            track.codec,
            channels,
            flags.commentary,
            flags.hearing_impaired,
            flags.forced,
            flags.visual_impaired,
        )

    def match(self) -> TrackMatch:
        # shortcut: a tag without a region also fits the regions of its language (`en` fits `en-US`), so the
        # signature of an `en` track reaches `en-US` tracks too; an exact language test in `TrackMatch` would fix it.
        return TrackMatch(
            kind=KindTest(self.kind.value),
            languages=[self.language],
            codecs=[self.codec] if self.codec else [],
            min_channels=self.channels or 0,
            max_channels=self.channels or 0,
            # Each flag set or unset, so the main track's rule does not reach the commentary beside it.
            forced=_test(self.forced),
            hearing_impaired=_test(self.hearing_impaired),
            visual_impaired=_test(self.visual_impaired),
            commentary=_test(self.commentary),
            # The whole name, so an unnamed track's signature does not reach the named tracks beside it.
            name="" if self.name is None else f"^{re.escape(self.name)}$",
            name_is_regex=self.name is not None,
        )


# A view asks for each track's signature several times per build; tracks are frozen, so a cached one stays right.
@lru_cache(maxsize=8192)
def _nameless(track: Track, flags_from_names: bool) -> TrackSignature:
    return TrackSignature._read(track, flags_from_names)


def _test(flag: bool) -> FlagTest:
    return FlagTest.SET if flag else FlagTest.UNSET


@dataclass(frozen=True, slots=True)
class TrackGroups:
    """How a batch's tracks fall into signatures. A group is told apart by name in every file of the batch when one
    file holds two of its tracks (two unflagged English AC-3 5.1 tracks): a rule without the name would fit both, and
    a name only in that one file would leave the group's rule fitting that file's named tracks too. Paired subtitle
    files beside the video count as that file's tracks whether added or not, so adding one changes no group, and a
    group a paired file shares with an embedded track of another file is told apart by name too."""

    flags_from_names: bool = True
    by_name: frozenset[TrackSignature] = field(default_factory=frozenset)

    @classmethod
    def of(cls, items: Iterable[MediaItem], flags_from_names: bool) -> TrackGroups:
        by_name: set[TrackSignature] = set()
        embedded: set[TrackSignature] = set()
        paired: set[TrackSignature] = set()
        for item in items:
            seen: set[TrackSignature] = set()
            files = [stand_in(subtitle, index) for index, subtitle in enumerate(item.subtitles)]
            for track in (*item.file.tracks, *files):
                signature = TrackSignature.of(track, flags_from_names)
                if signature in seen:
                    by_name.add(signature)
                seen.add(signature)
                (paired if track in files else embedded).add(signature)
        # An embedded track and a paired file alike in different files are one chip each, so their rules need the
        # name (a paired file has none) to stay apart.
        return cls(flags_from_names, frozenset(by_name | (embedded & paired)))

    def signature(self, track: Track) -> TrackSignature:
        signature = TrackSignature.of(track, self.flags_from_names)
        return replace(signature, name=track.name) if signature in self.by_name else signature


@dataclass(frozen=True, slots=True)
class TrackChoice:
    """`verdict` keeps or drops the tracks; `pass` leaves that to the other rules. `default` and `forced` give the
    flag to the first such track of its kind; a dropped track takes no flag."""

    verdict: Verdict = Verdict.PASS
    default: bool = False
    forced: bool = False


NO_CHOICE = TrackChoice()


def choice_of(options: TracksOptions, signature: TrackSignature) -> TrackChoice:
    """The choice the rules hold for `signature`; `NO_CHOICE` when none was made or its rule is paused, since a
    paused rule decides nothing. A new choice on it replaces the paused rule in its place, switched on."""
    index = _index(options.rules, signature)
    if index is None or not options.rules[index].enabled:
        return NO_CHOICE
    rule = options.rules[index]
    return TrackChoice(rule.verdict, rule.default is FlagShape.FIRST, rule.forced is FlagShape.FIRST)


def choose(options: TracksOptions, signature: TrackSignature, choice: TrackChoice) -> TracksOptions:
    """The options with `choice` as the rule for `signature`: a new rule, the old one changed in its place, or the
    old one removed for `NO_CHOICE`. A new choice goes after the choices that lead the list and before every other
    rule, so a second star becomes the fallback of the first ("default Turkish, else English")."""
    if choice.verdict is Verdict.DROP:
        choice = TrackChoice(Verdict.DROP)
    rules = list(options.rules)
    index = _index(rules, signature)
    if index is not None:
        del rules[index]
    if choice != NO_CHOICE:
        if index is None:
            index = next((n for n, rule in enumerate(rules) if not rule.from_choice), len(rules))
        rules.insert(
            index,
            TrackRule(
                match=signature.match(),
                verdict=choice.verdict,
                default=FlagShape.FIRST if choice.default else FlagShape.LEAVE,
                forced=FlagShape.FIRST if choice.forced else FlagShape.LEAVE,
                from_choice=True,
            ),
        )
    return replace(options, rules=rules)


def add_paired(options: TracksOptions, paired: PairedFile, add: bool) -> TracksOptions:
    """The options with the paired files of `paired` (`PairedFile.of(subtitle)`) added to the video or not. Once
    added, such a file is a subtitle track like the others: `choose` on its `TrackSignature` flags or drops it."""
    rest = [chosen for chosen in options.add_paired if chosen != paired]
    return replace(options, add_paired=[*rest, paired] if add else rest)


def move_rule(options: TracksOptions, source: int, target: int) -> TracksOptions:
    """The options with the rule at `source` moved to `target`, both positions in the list as it is now."""
    rules = list(options.rules)
    rules.insert(max(0, min(target, len(rules) - 1)), rules.pop(source))
    return replace(options, rules=rules)


def pause_rule(options: TracksOptions, index: int, paused: bool) -> TracksOptions:
    """The options with one rule paused (kept in the list, deciding nothing) or on again."""
    rules = list(options.rules)
    rules[index] = replace(rules[index], enabled=not paused)
    return replace(options, rules=rules)


def signature_of(rule: TrackRule, signatures: Iterable[TrackSignature]) -> TrackSignature | None:
    """The signature among `signatures` whose choice `rule` is, if it is one."""
    return next((s for s in signatures if rule.from_choice and rule.match == s.match()), None)


def _index(rules: list[TrackRule], signature: TrackSignature) -> int | None:
    match = signature.match()
    return next((n for n, rule in enumerate(rules) if rule.from_choice and rule.match == match), None)
