"""The subtitle work for one file: which finished subtitles it gets and the steps each needs. Pure logic: the plan names
the work and its inputs, and nothing is read, run or written until Apply.

A finished subtitle is one subtitle, in one language, that goes into the new file. It is made in three cases only:
a paired file the track plan adds gets the cleanup, sync and re-split the place asks for; a wanted language no
subtitle of the file has is translated from the reference; an embedded text track in a wanted language is cleaned.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from showrunner.core.cue import FORMATS
from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.track import Track, TrackKind
from showrunner.stages.subtitles.options import Approval, Lines, ReferenceKind, SubtitlesOptions, SyncEngine
from showrunner.stages.tracks import KindTest, PlanRefused, TrackMatch, TracksOptions, matches, plan_tracks, stand_in
from showrunner.tools.cleanit import RuleSet

PGS = "S_HDMV/PGS"  # the picture format OCR reads
# The language Automatic prefers for the reference: translation models translate best from English.
DEFAULT_REFERENCE_LANGUAGE = "en"
_TEXT_FORMATS = {"S_TEXT/ASS": "ass", "S_TEXT/SSA": "ssa", "S_TEXT/WEBVTT": "vtt"}


class StepKind(StrEnum):
    """The slow work of a finished subtitle, in the order it runs."""

    READ = "read"  # a text track taken out of the video
    OCR = "ocr"  # a picture track read as text, with the OCR fixes
    TRANSLATE = "translate"
    CLEAN = "clean"
    SYNC = "sync"
    RESPLIT = "resplit"
    # Not a step of `FinishedSubtitle.steps`: the wait for the user before the file's mux (`waits`), available like a
    # step once a view can approve.
    APPROVAL = "approval"


class Source(StrEnum):
    PAIRED = "paired"  # a subtitle file beside the video that the track plan adds
    EMBEDDED = "embedded"  # a text track of the video, replaced in the new file by its cleaned text
    TRANSLATION = "translation"  # made from the reference, for a wanted language the file lacks


class Cannot(StrEnum):
    """Why a finished subtitle the place asks for cannot be made in a file."""

    NO_REFERENCE = "no-reference"  # a translation needs a subtitle to translate from
    NO_TEXT_REFERENCE = "no-text-reference"  # re-split needs the reference's lines


@dataclass(frozen=True, slots=True)
class Step:
    kind: StepKind
    # CLEAN: the rule sets that cover the subtitle's language, sorted. TRANSLATE: the sets that cover the reference's
    # language, which clean it before it is translated.
    sets: tuple[str, ...] = ()
    # The fingerprint of those sets' rules, so a result made with other rules is not reused after a rule changed.
    rules: str = ""
    engine: SyncEngine = SyncEngine.AS_IT_IS  # SYNC
    settings: tuple[tuple[str, str], ...] = ()  # SYNC: the engine's own settings set on the place
    model: str = ""  # TRANSLATE, RESPLIT: empty for the model chosen in Settings


@dataclass(frozen=True, slots=True)
class ReferenceTrack:
    """What a file's sync, re-split and translation work against."""

    track: Track | None  # None: the audio
    # The place chose a group this file has no track of, so Automatic found this one. Not shown yet; the Reference
    # row is to name such files.
    fallback: bool = False

    @property
    def step(self) -> Step | None:
        """How the reference is read before the work that needs it; none for the audio."""
        if self.track is None:
            return None
        return Step(StepKind.OCR if self.track.codec == PGS else StepKind.READ)


@dataclass(frozen=True, slots=True)
class FinishedSubtitle:
    source: Source
    language: Language | None
    steps: tuple[Step, ...]
    format: str  # the extension of the result, without the dot: srt, ass, ssa or vtt
    paired: SubtitleFile | None = None  # PAIRED
    track: Track | None = None  # EMBEDDED
    # The file's mux waits until the user approves it.
    waits: bool = False
    cannot: tuple[Cannot, ...] = ()
    # The kinds of work it needs that this version cannot do, in the order they run; such a subtitle is left out.
    missing: tuple[StepKind, ...] = ()

    @property
    def uses_reference(self) -> bool:
        return any(step.kind in (StepKind.TRANSLATE, StepKind.SYNC, StepKind.RESPLIT) for step in self.steps)


@dataclass(frozen=True, slots=True)
class SubtitlePlan:
    video: Path
    # The ones that can be made, in the order they go into the new file after its own tracks.
    finished: tuple[FinishedSubtitle, ...] = ()
    reference: ReferenceTrack | None = None  # when a finished subtitle works against it
    # Asked for by the place, but impossible in this file; each says why.
    cannot: tuple[FinishedSubtitle, ...] = ()
    # Asked for by the place, but needing work that is not available (`missing`), so left out of this run: the file's
    # other changes go on without it, as they do without a missing program.
    left_out: tuple[FinishedSubtitle, ...] = ()

    @property
    def waits(self) -> bool:
        return any(finished.waits for finished in self.finished)


def plan_subtitles(
    item: MediaItem,
    options: SubtitlesOptions,
    tracks: TracksOptions,
    *,
    prefer: str = DEFAULT_REFERENCE_LANGUAGE,
    available: Collection[StepKind] = frozenset(StepKind),
    rule_sets: Mapping[str, RuleSet] | None = None,
) -> SubtitlePlan:
    """The finished subtitles the place's options ask for in this file. The paired files are the ones the track plan
    adds, so a run that leaves the track choices out leaves their subtitle work out too. `prefer` is the language
    Automatic looks for first in the reference. `available` are the kinds of work that can run: a finished subtitle
    that needs another one is left out. `rule_sets` are the cleanup sets that exist, by name: a subtitle is cleaned with
    the chosen sets whose rules cover its language."""
    rule_sets = rule_sets or {}
    video = item.file.path
    if options == _NOTHING:
        return SubtitlePlan(video)
    track_plan = plan_tracks(item, tracks)
    if isinstance(track_plan, PlanRefused):
        return SubtitlePlan(video)
    chosen = options.rule_sets()
    sync = (
        (Step(StepKind.SYNC, engine=options.sync, settings=options.engine_settings()),)
        if options.sync is not SyncEngine.AS_IT_IS
        else ()
    )
    resplit = (Step(StepKind.RESPLIT, model=options.model),) if sync and options.lines is Lines.RESPLIT else ()
    every = options.approval is Approval.EVERY

    found: list[FinishedSubtitle] = []
    for kept in track_plan.kept:
        if (paired := kept.external) is not None:
            format_ = FORMATS.get(paired.path.suffix.casefold())
            # A picture file beside the video has no text to clean, sync or re-split.
            if format_ is not None and (steps := _clean(chosen, rule_sets, paired.language) + sync + resplit):
                found.append(FinishedSubtitle(Source.PAIRED, paired.language, steps, format_, paired, waits=every))
        elif (
            _text(kept.track)
            and (clean := _clean(chosen, rule_sets, kept.track.language))
            and _wanted(kept.track, options)
        ):
            # An embedded track is timed to its own video, so it is cleaned and never synced.
            steps = (Step(StepKind.READ), *clean)
            found.append(
                FinishedSubtitle(
                    Source.EMBEDDED,
                    kept.track.language,
                    steps,
                    _track_format(kept.track),
                    track=kept.track,
                    waits=every,
                )
            )
    # A translation takes the reference's timing, so it is not synced either.
    absent = [tag for tag in options.wanted() if not _present(item, tag)]
    reference = _reference(item, options, prefer) if absent or sync else None
    for tag in absent:
        if (language := Language.parse(tag)) is not None:
            # The reference is cleaned for its own language before it is translated, the translation for its own.
            source = reference.track.language if reference is not None and reference.track is not None else None
            names, rules = _covering(chosen, rule_sets, source)
            steps = (Step(StepKind.TRANSLATE, names, rules, model=options.model), *_clean(chosen, rule_sets, language))
            waits = every or options.approval is Approval.TRANSLATIONS
            found.append(FinishedSubtitle(Source.TRANSLATION, language, steps, "srt", waits=waits))

    ready, cannot, left_out = [], [], []
    for finished in found:
        if reasons := _reasons(finished, reference):
            cannot.append(replace(finished, cannot=reasons))
        elif missing := _missing(finished, reference, available):
            left_out.append(replace(finished, missing=missing))
        else:
            ready.append(finished)
    if not any(finished.uses_reference for finished in ready):
        reference = None
    return SubtitlePlan(video, tuple(ready), reference, tuple(cannot), tuple(left_out))


_NOTHING = SubtitlesOptions()


def _covering(
    chosen: tuple[str, ...], rule_sets: Mapping[str, RuleSet], language: Language | None
) -> tuple[tuple[str, ...], str]:
    """The chosen sets that exist and work on `language`, and the fingerprint of their rules. A set that was deleted
    or whose file is broken is left out, and so is a set whose rules are all for other languages."""
    names = tuple(name for name in chosen if (found := rule_sets.get(name)) is not None and found.covers(language))
    return names, "+".join(f"{name}:{rule_sets[name].fingerprint}" for name in names)


def _clean(chosen: tuple[str, ...], rule_sets: Mapping[str, RuleSet], language: Language | None) -> tuple[Step, ...]:
    names, rules = _covering(chosen, rule_sets, language)
    return (Step(StepKind.CLEAN, names, rules),) if names else ()


def _reasons(finished: FinishedSubtitle, reference: ReferenceTrack | None) -> tuple[Cannot, ...]:
    no_text = reference is None or reference.track is None
    kinds = {step.kind for step in finished.steps}
    reasons = []
    if StepKind.TRANSLATE in kinds and no_text:
        reasons.append(Cannot.NO_REFERENCE)
    if StepKind.RESPLIT in kinds and no_text:
        reasons.append(Cannot.NO_TEXT_REFERENCE)
    return tuple(reasons)


def _missing(
    finished: FinishedSubtitle, reference: ReferenceTrack | None, available: Collection[StepKind]
) -> tuple[StepKind, ...]:
    """The kinds of work the finished subtitle needs that are not available: its steps, the reading of the reference
    it works against, and the wait for approval."""
    needed = {step.kind for step in finished.steps}
    if finished.uses_reference and reference is not None and (read := reference.step) is not None:
        needed.add(read.kind)
    if finished.waits:
        needed.add(StepKind.APPROVAL)
    return tuple(kind for kind in StepKind if kind in needed and kind not in available)


def _reference(item: MediaItem, options: SubtitlesOptions, prefer: str) -> ReferenceTrack:
    chosen = options.reference
    if chosen.kind is ReferenceKind.AUDIO:
        return ReferenceTrack(None)
    subtitles = item.file.subtitle_tracks
    chosen_track = next((t for t in subtitles if matches(chosen.track, t)), None)
    if chosen.kind is ReferenceKind.TRACK and chosen_track is not None:
        return ReferenceTrack(chosen_track)
    preferred = TrackMatch(kind=KindTest.SUBTITLE, languages=[prefer])
    picture = [t for t in subtitles if t.codec == PGS]
    text = [t for t in subtitles if _text(t)]
    in_language = [t for t in (*text, *picture) if matches(preferred, t)]
    track = next(iter((*in_language, *text, *picture)), None)
    return ReferenceTrack(track, fallback=chosen.kind is ReferenceKind.TRACK)


def _text(track: Track) -> bool:
    return track.kind is TrackKind.SUBTITLE and track.subtitle is not None and track.subtitle.text_based


def _track_format(track: Track) -> str:
    return _TEXT_FORMATS.get(track.codec.upper(), "srt")


def _wanted(track: Track, options: SubtitlesOptions) -> bool:
    return any(_fits(tag, track) for tag in options.wanted())


def _present(item: MediaItem, tag: str) -> bool:
    """Whether any subtitle of the file is in the language: a track of any kind, or a paired file, added or not."""
    files = (stand_in(subtitle, index) for index, subtitle in enumerate(item.subtitles))
    return any(_fits(tag, track) for track in (*item.file.subtitle_tracks, *files))


def _fits(tag: str, track: Track) -> bool:
    return matches(TrackMatch(kind=KindTest.SUBTITLE, languages=[tag]), track)
