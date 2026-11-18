"""Choices made directly on a track (keep, drop, default, forced) written as ordinary track rules, the choice to add
a paired subtitle file, and the order of the tracks in the new file.

A choice is made on a track signature, the group of alike tracks across a batch that one chip or matrix column
stands for. It becomes one rule marked `from_choice`, so what a chip shows is what the rules produce: there is no
second layer of choices the engine cannot see. Choice rules lead the rule list, because the first rule that decides
wins and a click on a chip has to take effect over a hand-written rule that says otherwise; the hand-written rule
itself is never edited.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
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
    SourceTest,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
    is_paired,
    order_places,
    stand_in,
)


@dataclass(frozen=True, slots=True)
class TrackSignature:
    """What makes tracks alike across a batch: kind, language, codec, channels, what the track is (commentary,
    hearing impaired, forced, audio description) and where it comes from (inside the file or a paired file beside
    it), read as the rules read them. Default is not part of it, since a choice changes it. The name is not either,
    so tracks named after each episode are one group; only a group that `TrackGroups` tells apart by name carries
    it."""

    kind: TrackKind
    language: str  # IETF tag, `und` for a track without one
    codec: str  # Matroska codec ID
    channels: int | None  # audio only
    commentary: bool = False
    hearing_impaired: bool = False
    forced: bool = False
    visual_impaired: bool = False
    paired: bool = False  # a paired subtitle file beside the video, not a track inside it
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
            is_paired(track),
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
            # Only subtitles come from paired files; audio and video rules stay as they were without the test.
            source=(SourceTest.PAIRED if self.paired else SourceTest.EMBEDDED)
            if self.kind is TrackKind.SUBTITLE
            else SourceTest.ANY,
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
    files beside the video count as that file's tracks whether added or not, so adding one changes no group. A paired
    file and an embedded track are never one group, since where a track comes from is part of the signature."""

    flags_from_names: bool = True
    by_name: frozenset[TrackSignature] = field(default_factory=frozenset)

    @classmethod
    def of(cls, items: Iterable[MediaItem], flags_from_names: bool) -> TrackGroups:
        by_name: set[TrackSignature] = set()
        for item in items:
            seen: set[TrackSignature] = set()
            files = [stand_in(subtitle, index) for index, subtitle in enumerate(item.subtitles)]
            for track in (*item.file.tracks, *files):
                signature = TrackSignature.of(track, flags_from_names)
                if signature in seen:
                    by_name.add(signature)
                seen.add(signature)
        return cls(flags_from_names, frozenset(by_name))

    def signature(self, track: Track) -> TrackSignature:
        signature = TrackSignature.of(track, self.flags_from_names)
        return replace(signature, name=track.name) if signature in self.by_name else signature


@dataclass(frozen=True, slots=True)
class TrackChoice:
    """`verdict` keeps or drops the tracks; `pass` leaves that to the other rules. `default` and `forced` give the
    flag to the first such track of its kind; a dropped track takes no flag. `language` is the IETF tag the tracks get,
    empty to leave theirs; it is kept when a drop is undone, since the track may come back."""

    verdict: Verdict = Verdict.PASS
    default: bool = False
    forced: bool = False
    language: str = ""


NO_CHOICE = TrackChoice()


def choice_of(options: TracksOptions, signature: TrackSignature) -> TrackChoice:
    """The choice the rules hold for `signature`; `NO_CHOICE` when none was made or its rule is paused, since a
    paused rule decides nothing. A new choice on it replaces the paused rule in its place, switched on."""
    index = choice_index(options.rules, signature)
    if index is None or not options.rules[index].enabled:
        return NO_CHOICE
    return _choice(options.rules[index])


def choose(
    options: TracksOptions,
    signature: TrackSignature,
    choice: TrackChoice,
    inherited: TrackChoice = NO_CHOICE,
    lead: bool = False,
) -> TracksOptions:
    """The options with `choice` as the rule for `signature`: a new rule, the old one changed in its place, or the
    old one removed when `choice` is what the place receives from above (`inherited`; nothing for a place without a
    parent), so it follows its parent again. Any other choice is written, `NO_CHOICE` too, as a rule that decides
    nothing and hides the parent's choice (see `layered_rules`). A new choice goes after the choices that lead the
    list and before every other rule, so a second star becomes the fallback of the first ("default Turkish, else
    English"). With `lead`, a new rule goes first of all: the choice on one name of a chip (`named`) has to be tried
    before the chip's own choice, which fits every name."""
    if choice.verdict is Verdict.DROP:
        choice = TrackChoice(Verdict.DROP, language=choice.language)
    rules = list(options.rules)
    index = choice_index(rules, signature)
    if index is not None:
        del rules[index]
    if choice != inherited:
        if index is None:
            index = 0 if lead else next((n for n, rule in enumerate(rules) if not rule.from_choice), len(rules))
        rules.insert(
            index,
            TrackRule(
                match=signature.match(),
                verdict=choice.verdict,
                default=FlagShape.FIRST if choice.default else FlagShape.LEAVE,
                forced=FlagShape.FIRST if choice.forced else FlagShape.LEAVE,
                language=choice.language,
                from_choice=True,
            ),
        )
    return replace(options, rules=rules)


def named(signature: TrackSignature, name: str) -> TrackSignature:
    """The signature of one name of a chip's tracks, which `choose` writes as a narrow rule: the chip's match with
    the whole name, so the rule fits no other name and decides first when placed ahead of the chip's own rule."""
    return replace(signature, name=name)


def name_of_rule(rule: TrackRule, signatures: Iterable[TrackSignature]) -> TrackSignature | None:
    """The named signature (see `named`) among the chips of `signatures` whose choice `rule` is, if it is one: a
    rule written for one name of a chip."""
    pattern = rule.match.name
    if not (rule.from_choice and rule.match.name_is_regex and pattern.startswith("^") and pattern.endswith("$")):
        return None
    name = re.sub(r"\\(.)", r"\1", pattern[1:-1])  # undoes `re.escape`
    found = (named(s, name) for s in signatures if s.name is None)
    return next((n for n in found if rule.match in _forms(n)), None)


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


def add_rule(options: TracksOptions, rule: TrackRule) -> TracksOptions:
    """The options with a hand-written rule at the end of the list. First match wins, so the last place never takes a
    decision from the choices that lead the list or from a rule written before; a drag moves it up when it should."""
    return replace(options, rules=[*options.rules, rule])


def replace_rule(options: TracksOptions, index: int, rule: TrackRule) -> TracksOptions:
    """The options with the rule at `index` replaced in its place."""
    rules = list(options.rules)
    rules[index] = rule
    return replace(options, rules=rules)


def pause_rule(options: TracksOptions, index: int, paused: bool) -> TracksOptions:
    """The options with one rule paused (kept in the list, deciding nothing) or on again."""
    rules = list(options.rules)
    rules[index] = replace(rules[index], enabled=not paused)
    return replace(options, rules=rules)


def in_order(signatures: Sequence[TrackSignature], options: TracksOptions) -> list[int]:
    """The places of `signatures` as `TracksOptions.order` puts their tracks in a new file, as indices into
    `signatures`: within each kind the ones it names first, in its order, then the rest as they were."""
    order = options.order
    if not order:
        return list(range(len(signatures)))
    matches = [s.match() for s in signatures]
    ranks = [next((n for n, m in enumerate(order) if m == match), len(order)) for match in matches]
    return order_places([s.kind for s in signatures], ranks)


def move_track(
    options: TracksOptions,
    shown: Sequence[TrackSignature],
    natural: Sequence[TrackSignature],
    source: int,
    target: int,
) -> TracksOptions:
    """The options with the track at `source` of `shown` (the batch's signatures in the order the new files get them,
    each kind's together) moved to `target`, kept among the tracks of its kind. An order that comes out as `natural`,
    the order without one, is stored as none, so moving a track back plans nothing."""
    places = [n for n, s in enumerate(shown) if s.kind is shown[source].kind]
    moved = list(shown)
    moved.insert(max(places[0], min(target, places[-1])), moved.pop(source))
    return replace(options, order=[] if moved == list(natural) else [s.match() for s in moved])


def layered_rules(own: Sequence[TrackRule], inherited: Sequence[TrackRule]) -> list[TrackRule]:
    """A place's rules over the rules it receives: its own first, since the first rule that decides wins, then the
    received ones without the choices its own choices replace. Hiding them matters for the flags: a `first` star
    from above would otherwise still pick a track the place took the star from. A paused choice decides nothing, so
    it hides nothing either."""
    hidden = [form for rule in own if rule.from_choice and rule.enabled for form in _rule_forms(rule)]
    return [*own, *(rule for rule in inherited if not (rule.from_choice and rule.match in hidden))]


def repeats_received(rule: TrackRule, received: Sequence[TrackRule]) -> bool:
    """Whether an own choice says what the place receives on the same tracks (none received counting as no choice),
    as `choose` would have left no rule. A paused choice and a hand-written rule never do."""
    if not (rule.from_choice and rule.enabled):
        return False
    forms = _rule_forms(rule)
    given = next((r for r in received if r.from_choice and r.match in forms), None)
    return _choice(rule) == (_choice(given) if given is not None and given.enabled else NO_CHOICE)


def _choice(rule: TrackRule) -> TrackChoice:
    return TrackChoice(rule.verdict, rule.default is FlagShape.FIRST, rule.forced is FlagShape.FIRST, rule.language)


def _rule_forms(rule: TrackRule) -> tuple[TrackMatch, TrackMatch]:
    return rule.match, replace(rule.match, source=SourceTest.ANY)


def signature_of(rule: TrackRule, signatures: Iterable[TrackSignature]) -> TrackSignature | None:
    """The signature among `signatures` whose choice `rule` is, if it is one."""
    return next((s for s in signatures if rule.from_choice and rule.match in _forms(s)), None)


def choice_index(rules: list[TrackRule], signature: TrackSignature) -> int | None:
    forms = _forms(signature)
    return next((n for n, rule in enumerate(rules) if rule.from_choice and rule.match in forms), None)


def _forms(signature: TrackSignature) -> tuple[TrackMatch, TrackMatch]:
    """The match a choice on `signature` writes, and the same without the source test, as subtitle choices were
    stored before it: the chip owns such a rule, so a click rewrites it in its place instead of losing to it."""
    match = signature.match()
    return match, replace(match, source=SourceTest.ANY)
