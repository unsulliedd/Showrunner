"""The subtitle work for one file: which finished subtitles it gets and the steps each needs. Pure logic: the plan names
the work and its inputs, and nothing is read, run or written until Apply.

A finished subtitle is one subtitle, in one language, that goes into the new file or beside the video, as the place's
Output asks. It is made in three cases only: a paired file gets the cleanup, sync and re-split the place asks for (into
the video only where the track plan adds it, beside the video whether it does or not); a wanted language is translated
from the reference where no subtitle of the file has it, or wherever the place asks for a translation always; an
embedded text track in a wanted language is cleaned.
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
from showrunner.stages.subtitles.beside import is_result, language_name, new_file_name
from showrunner.stages.subtitles.options import (
    Approval,
    Lines,
    Output,
    ReferenceKind,
    SubtitlesOptions,
    SyncEngine,
    Translate,
)
from showrunner.stages.subtitles.prompt import DEFAULT_CONTEXT, DEFAULT_WINDOW
from showrunner.stages.tracks import KindTest, PlanRefused, TrackMatch, TracksOptions, matches, plan_tracks, stand_in
from showrunner.tools.cleanit import RuleSet
from showrunner.tools.ocr import tesseract_code

PGS = "S_HDMV/PGS"  # the picture format OCR reads
# The language Automatic prefers for the reference: translation models translate best from English.
DEFAULT_REFERENCE_LANGUAGE = "en"
_TEXT_FORMATS = {"S_TEXT/ASS": "ass", "S_TEXT/SSA": "ssa", "S_TEXT/WEBVTT": "vtt"}


class StepKind(StrEnum):
    """The slow work of a finished subtitle, in the order it runs."""

    READ = "read"  # a text track taken out of the video
    OCR = "ocr"  # a picture track read as text, with the OCR fixes
    # The sound read as speech, which a sync against the audio needs. Not a step of `FinishedSubtitle.steps`: only a
    # kind of work a plan can miss (`missing`), where the program that reads the sound is not there.
    AUDIO = "audio"
    # Not steps either: an AI server that answers, and the model a translation or re-split asks for installed on it.
    AI = "ai"
    MODEL = "model"
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
    TRANSLATION = "translation"  # made from the reference, for a wanted language the file lacks or for every one


class Cannot(StrEnum):
    """Why a finished subtitle the place asks for cannot be made in a file."""

    NO_REFERENCE = "no-reference"  # a translation needs a subtitle to translate from
    NO_TEXT_REFERENCE = "no-text-reference"  # re-split needs the reference's lines
    # Beside the video: a file of the name it would be written to lies there already, or another finished subtitle of
    # the file is written to it. Never overwritten.
    TARGET_EXISTS = "target-exists"


@dataclass(frozen=True, slots=True)
class Step:
    kind: StepKind
    # CLEAN: the rule sets that cover the subtitle's language, sorted. TRANSLATE: the sets that cover the reference's
    # language, which clean it before it is translated.
    sets: tuple[str, ...] = ()
    # The fingerprint of those sets' rules, so a result made with other rules is not reused after a rule changed.
    rules: str = ""
    engine: SyncEngine = SyncEngine.AS_IT_IS  # SYNC
    # SYNC: the engine's own settings set on the place. TRANSLATE: the window size and context, from Settings.
    settings: tuple[tuple[str, str], ...] = ()
    # TRANSLATE, RESPLIT: the model, the one chosen in Settings where the place chose none, so a result made by another
    # model is not reused. Empty where no model is known: none is chosen, or no server answers.
    model: str = ""


@dataclass(frozen=True, slots=True)
class AiModels:
    """The AI models the plans may use."""

    default: str = ""  # chosen in Settings, for a place that chooses none
    installed: tuple[str, ...] = ()
    window: int = DEFAULT_WINDOW  # the cues a translation asks the model for at a time
    context: int = DEFAULT_CONTEXT  # the cues before and after a window sent along to read it in its scene


_AI_KINDS = (StepKind.TRANSLATE, StepKind.RESPLIT)


@dataclass(frozen=True, slots=True)
class ReferenceTrack:
    """What a file's sync, re-split and translation work against."""

    track: Track | None  # None: the audio
    # The place chose a group this file has no track of, so Automatic found this one; the Reference row and Review name
    # such files.
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
    # Where the subtitle stage writes it beside the video; None for one that goes into the new file through Mux.
    target: Path | None = None
    # TRANSLATION: the file has a subtitle in its language already, which stays as it is next to this one.
    existing: bool = False
    # The track name it gets in the new file; empty leaves it unnamed.
    name: str = ""

    @property
    def replaces(self) -> bool:
        """Written in place of its paired file, which goes to the Recycle Bin once the new one is checked."""
        return self.paired is not None and self.target == self.paired.path

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
    # Text subtitle files beside the video that the track plan does not add: the place's subtitle work cannot reach
    # them until Tracks adds them.
    not_added: tuple[SubtitleFile, ...] = ()
    # Beside the video as new files: the ones whose new file the scan found beside the video, named with the place's
    # new-file text, so an earlier run wrote it and nothing is planned for them; so too a translation made whatever
    # subtitles exist, whose file named with the AI text lies beside the video, or whose named track the video holds
    # (`target` None).
    written_earlier: tuple[FinishedSubtitle, ...] = ()

    @property
    def waits(self) -> bool:
        return any(finished.waits for finished in self.finished)

    @property
    def into_video(self) -> tuple[FinishedSubtitle, ...]:
        """The finished subtitles that go into the new file, so the video needs one for them."""
        return tuple(finished for finished in self.finished if finished.target is None)

    @property
    def written(self) -> tuple[Path, ...]:
        """The files the subtitle stage writes beside the video."""
        return tuple(finished.target for finished in self.finished if finished.target is not None)


def plan_subtitles(
    item: MediaItem,
    options: SubtitlesOptions,
    tracks: TracksOptions,
    *,
    prefer: str = DEFAULT_REFERENCE_LANGUAGE,
    available: Collection[StepKind] = frozenset(StepKind),
    rule_sets: Mapping[str, RuleSet] | None = None,
    ocr_languages: Collection[str] | None = None,
    syncs: Mapping[SyncEngine, bool] | None = None,
    ai: AiModels | None = None,
) -> SubtitlePlan:
    """The finished subtitles the place's options ask for in this file. Into the video, the paired files are the ones
    the track plan adds, so a run that leaves the track choices out leaves their subtitle work out too; beside the
    video, every text file paired with the video is worked on, but for the ones an earlier run named with the new-file
    text. A new file the scan already paired with the video was written by an earlier run, so its original plans no work
    (`written_earlier`); any other target that names a file the scan paired with the video, other than the one it
    replaces, or another subtitle's target, cannot be written. The plan reads nothing from disk, so Apply checks again
    before it writes. `prefer` is the language Automatic looks for first in the reference. `available` are the kinds of
    work that can run: a finished subtitle that needs another one is left out. `rule_sets` are the cleanup sets that
    exist, by name: a subtitle is cleaned with the chosen sets whose rules cover its language. `ocr_languages` are the
    Tesseract models installed, so a picture reference in a language with none cannot be read; None leaves that
    unchecked. `syncs` are the sync engines that can run, each with whether it can work against the audio; a sync with
    another engine, or against the audio with one that cannot, is left out. None leaves that unchecked. `ai` gives a
    place that chooses no model the Settings one, and the work of a model that is not installed is left out; None leaves
    both as the place has them."""
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
    model = options.model or (ai.default if ai is not None else "")
    windows = ai or AiModels()
    windowing = (("context", str(windows.context)), ("window", str(windows.window)))
    resplit = (Step(StepKind.RESPLIT, model=model),) if sync and options.lines is Lines.RESPLIT else ()
    every = options.approval is Approval.EVERY
    beside = options.output is not Output.VIDEO

    found: list[FinishedSubtitle] = []

    def add_paired(paired: SubtitleFile) -> None:
        # A translation an earlier run wrote beside the video is a result, never a source to work on again.
        if is_result(paired.path.name, options.ai_file_text):
            return
        format_ = FORMATS.get(paired.path.suffix.casefold())
        # A picture file beside the video has no text to clean, sync or re-split.
        if format_ is not None and (steps := _clean(chosen, rule_sets, paired.language) + sync + resplit):
            found.append(FinishedSubtitle(Source.PAIRED, paired.language, steps, format_, paired, waits=every))

    for kept in track_plan.kept:
        if kept.external is not None:
            if not beside:
                add_paired(kept.external)
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
                    track_format(kept.track),
                    track=kept.track,
                    waits=every,
                )
            )
    if beside:
        for paired in item.subtitles:
            if options.output is not Output.NEW_FILE or not is_result(paired.path.name, options.new_file_text):
                add_paired(paired)
    # A translation takes the reference's timing, so it is not synced either.
    always = options.translate is Translate.ALWAYS
    translated = [tag for tag in options.wanted() if always or not _present(item, tag)]
    reference = choose_reference(item, options, prefer, tracks.flags_from_names) if translated or sync else None
    earlier: list[FinishedSubtitle] = []
    for tag in translated:
        # The reference's own language is never translated from itself.
        if always and reference is not None and reference.track is not None and _fits(tag, reference.track):
            continue
        if (language := Language.parse(tag)) is not None:
            # The reference is cleaned for its own language before it is translated, the translation for its own.
            source = reference.track.language if reference is not None and reference.track is not None else None
            names, rules = _covering(chosen, rule_sets, source)
            translate = Step(StepKind.TRANSLATE, names, rules, settings=windowing, model=model)
            steps = (translate, *_clean(chosen, rule_sets, language))
            waits = every or options.approval is Approval.TRANSLATIONS
            name = options.ai_track_name.strip() if always else ""
            translation = FinishedSubtitle(
                Source.TRANSLATION,
                language,
                steps,
                "srt",
                waits=waits,
                existing=always and _present(item, tag),
                name=name,
            )
            if (
                always
                and not beside
                and any(_fits(tag, t) for t in item.file.subtitle_tracks if is_ai_track(t, options))
            ):
                earlier.append(translation)
            else:
                found.append(translation)

    ready, cannot, left_out = [], [], []
    # Compared without case, as Windows names files.
    scanned = {str(subtitle.path).casefold() for subtitle in item.subtitles}
    taken = set(scanned)
    for finished in found:
        reasons = _reasons(finished, reference)
        if beside:
            finished = replace(finished, target=_target(finished, video, options))
            key = str(finished.target).casefold()
            # Named with the new-file text after its own paired file, or with the AI text after the video, so it is the
            # result of an earlier run.
            named = options.output is Output.NEW_FILE and finished.paired is not None
            result = key in scanned and (named or (always and finished.source is Source.TRANSLATION))
            if result:
                earlier.append(finished)
                taken.add(key)
                continue
            if key in taken and not finished.replaces:
                reasons += (Cannot.TARGET_EXISTS,)
            taken.add(key)
        if reasons:
            cannot.append(replace(finished, cannot=reasons))
        elif missing := _missing(finished, reference, available, ocr_languages, syncs, ai):
            left_out.append(replace(finished, missing=missing))
        else:
            ready.append(finished)
    if not any(finished.uses_reference for finished in ready):
        reference = None
    added = {kept.external.path for kept in track_plan.kept if kept.external is not None}
    # Beside the video the work reaches every paired file, so none waits for Tracks to add it.
    not_added = (
        ()
        if beside
        else tuple(s for s in item.subtitles if s.path not in added and s.path.suffix.casefold() in FORMATS)
    )
    return SubtitlePlan(video, tuple(ready), reference, tuple(cannot), tuple(left_out), not_added, tuple(earlier))


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


def _target(finished: FinishedSubtitle, video: Path, options: SubtitlesOptions) -> Path:
    """Where a finished subtitle is written beside the video: in place of its paired file, beside it named with the
    new-file text, or, for one with no file of its own, named by its language."""
    if finished.paired is None:
        flags = finished.track.flags if finished.track is not None else None
        forced, sdh = (flags.forced, flags.hearing_impaired) if flags is not None else (False, False)
        always = finished.source is Source.TRANSLATION and options.translate is Translate.ALWAYS
        stem = video.stem + options.ai_file_text if always else video.stem
        return video.with_name(language_name(stem, finished.language, finished.format, forced=forced, sdh=sdh))
    path = finished.paired.path
    if options.output is Output.REPLACE:
        return path
    return path.with_name(new_file_name(path.name, options.new_file_text))


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
    finished: FinishedSubtitle,
    reference: ReferenceTrack | None,
    available: Collection[StepKind],
    ocr_languages: Collection[str] | None,
    syncs: Mapping[SyncEngine, bool] | None,
    ai: AiModels | None,
) -> tuple[StepKind, ...]:
    """The kinds of work the finished subtitle needs that are not available: its steps, the reading of the reference
    it works against, and the wait for approval. Reading a picture reference is not available either where Tesseract
    has no model for its language, and syncing is not where the engine it asks for cannot run or cannot work against
    the audio the reference is. AI work needs a server that answers and its model installed there."""
    needed = {step.kind for step in finished.steps}
    lacking: set[StepKind] = set()
    if finished.uses_reference and reference is not None and (read := reference.step) is not None:
        needed.add(read.kind)
        if (
            read.kind is StepKind.OCR
            and ocr_languages is not None
            and reference.track is not None
            and tesseract_code(reference.track.language) not in ocr_languages
        ):
            lacking.add(StepKind.OCR)
    for step in finished.steps if syncs is not None else ():
        if step.kind is not StepKind.SYNC:
            continue
        if step.engine not in syncs:  # type: ignore[operator]
            lacking.add(StepKind.SYNC)
        elif reference is not None and reference.track is None and not syncs[step.engine]:  # type: ignore[index]
            needed.add(StepKind.AUDIO)
            lacking.add(StepKind.AUDIO)
    for step in finished.steps:
        if step.kind in _AI_KINDS:
            needed.add(StepKind.AI)
            if ai is not None and step.model not in ai.installed:
                needed.add(StepKind.MODEL)
                lacking.add(StepKind.MODEL)
    if finished.waits:
        needed.add(StepKind.APPROVAL)
    return tuple(kind for kind in StepKind if kind in needed and (kind not in available or kind in lacking))


def choose_reference(
    item: MediaItem,
    options: SubtitlesOptions,
    prefer: str = DEFAULT_REFERENCE_LANGUAGE,
    flags_from_names: bool = True,
) -> ReferenceTrack:
    """The track a file's sync, re-split and translation work against: the place's choice where the file has a track of
    that group, else Automatic's, which is a track in the `prefer` language first, a text track before a picture one.
    The flags a track's name implies count as set when `flags_from_names`, as in the groups of the Tracks tab."""
    chosen = options.reference
    if chosen.kind is ReferenceKind.AUDIO:
        return ReferenceTrack(None)
    # A translation an earlier run made is never translated from again.
    subtitles = [t for t in item.file.subtitle_tracks if not is_ai_track(t, options)]
    chosen_track = next((t for t in subtitles if matches(chosen.track, t, flags_from_name=flags_from_names)), None)
    if chosen.kind is ReferenceKind.TRACK and chosen_track is not None:
        return ReferenceTrack(chosen_track)
    preferred = TrackMatch(kind=KindTest.SUBTITLE, languages=[prefer])
    picture = [t for t in subtitles if t.codec == PGS]
    text = [t for t in subtitles if _text(t)]
    in_language = [t for t in (*text, *picture) if matches(preferred, t, flags_from_name=flags_from_names)]
    track = next(iter((*in_language, *text, *picture)), None)
    return ReferenceTrack(track, fallback=chosen.kind is ReferenceKind.TRACK)


def is_ai_track(track: Track, options: SubtitlesOptions) -> bool:
    """Whether the track is a translation an earlier run put into the video, named with the AI track name.

    shortcut: known by its name only, so a track renamed since (by Names or by hand) is translated again and can be the
    reference; mark the track itself once the mux can write a tag of its own."""
    name = options.ai_track_name.strip().casefold()
    return track.kind is TrackKind.SUBTITLE and bool(name) and track.name.strip().casefold() == name


def _text(track: Track) -> bool:
    return track.kind is TrackKind.SUBTITLE and track.subtitle is not None and track.subtitle.text_based


def track_format(track: Track) -> str:
    """The extension a text track has outside the video: what mkvextract writes it as."""
    return _TEXT_FORMATS.get(track.codec.upper(), "srt")


def _wanted(track: Track, options: SubtitlesOptions) -> bool:
    return any(_fits(tag, track) for tag in options.wanted())


def _present(item: MediaItem, tag: str) -> bool:
    """Whether any subtitle of the file is in the language: a track of any kind, or a paired file, added or not."""
    files = (stand_in(subtitle, index) for index, subtitle in enumerate(item.subtitles))
    return any(_fits(tag, track) for track in (*item.file.subtitle_tracks, *files))


def _fits(tag: str, track: Track) -> bool:
    return matches(TrackMatch(kind=KindTest.SUBTITLE, languages=[tag]), track)
