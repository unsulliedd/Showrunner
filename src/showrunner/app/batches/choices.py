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
from dataclasses import dataclass, replace

from showrunner.core.track import Track, TrackKind
from showrunner.stages.tracks import (
    NO_LANGUAGE,
    FlagShape,
    KindTest,
    PairedFile,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
)


@dataclass(frozen=True, slots=True)
class TrackSignature:
    """What makes tracks alike across a batch. Default and forced are not part of it, since a choice changes them;
    the name is, so a commentary track named as one stays apart from the main track of its language."""

    kind: TrackKind
    language: str  # IETF tag, `und` for a track without one
    codec: str  # Matroska codec ID
    channels: int | None  # audio only
    name: str

    @classmethod
    def of(cls, track: Track) -> TrackSignature:
        language = track.language.ietf if track.language else NO_LANGUAGE
        channels = track.audio.channels if track.audio else None
        return cls(track.kind, language, track.codec, channels, track.name)

    def match(self) -> TrackMatch:
        # shortcut: a tag without a region also fits the regions of its language (`en` fits `en-US`), so the
        # signature of an `en` track reaches `en-US` tracks too; an exact language test in `TrackMatch` would fix it.
        return TrackMatch(
            kind=KindTest(self.kind.value),
            languages=[self.language],
            codecs=[self.codec] if self.codec else [],
            min_channels=self.channels or 0,
            max_channels=self.channels or 0,
            # The whole name, so an unnamed track's signature does not reach the named tracks beside it.
            name=f"^{re.escape(self.name)}$",
            name_is_regex=True,
        )


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
