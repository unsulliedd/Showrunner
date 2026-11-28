"""The shape every stage has for the job queue: plan one file, apply one plan. The stage engines stay as they are;
the classes here only adapt them."""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Protocol

from showrunner.app.ai import AI
from showrunner.app.jobs.hashing import FileStamp, stamp
from showrunner.app.jobs.results import ResultStore
from showrunner.app.profiles.profile import Profile
from showrunner.app.rules import RULES
from showrunner.app.storage.paths import results_dir
from showrunner.core.cue import read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.stages.metadata import MetadataPlan, MetadataRefused, apply_metadata, plan_metadata
from showrunner.stages.mux import Failure, MuxPlan, MuxRefused, MuxResult, apply_mux, plan_mux, resume_mux
from showrunner.stages.subtitles import AiModels, Step, StepKind, SubtitlePlan, SyncEngine, plan_subtitles
from showrunner.stages.subtitles.beside import (
    BesideError,
    BesideFailure,
    finish_replace,
    reads_as_original,
    write_beside,
)
from showrunner.stages.subtitles.clean import clean_runner
from showrunner.stages.subtitles.read import ocr_runner, read_runner
from showrunner.stages.subtitles.sync import sync_runner
from showrunner.stages.subtitles.translate import read_report, translate_runner
from showrunner.stages.subtitles.work import Runner, StepWork
from showrunner.stages.tracks import PlanRefused, plan_tracks
from showrunner.tools.cleanit import OCR_EXTRA, OCR_SET, RuleBook, RuleSet
from showrunner.tools.ocr import READING, installed_languages, model_stamp
from showrunner.tools.probe import Programs
from showrunner.tools.recycle import recycle
from showrunner.tools.sync import ENGINES, SyncAdapter

StepProgress = Callable[[float], None]  # the fraction of the step done, from 0 to 1
# The sync engines that can run, each with whether it can work against the audio; sorted, so it can be part of a stamp.
type SyncSupport = tuple[tuple[SyncEngine, bool], ...]


class PlanState(StrEnum):
    CHANGES = "changes"
    UNCHANGED = "unchanged"
    REFUSED = "refused"  # the stage's own refusal is in `plan`
    BLOCKED = "blocked"  # the stage's options have a problem, so it was not planned for any file


@dataclass(frozen=True, slots=True)
class StagePlan:
    stage: str
    state: PlanState
    # The stage's own plan or refusal (`TrackPlan`, `MetadataRefused`, ...), for the views; None when blocked.
    plan: object = None
    # True when this stage's `apply` has something to write. A stage can have changes that another one writes:
    # the track rules decide the flags, and Metadata or a remux writes them.
    writes: bool = False
    # Only a stage that writes a new file can carry the plan out.
    needs_remux: bool = False


@dataclass(frozen=True, slots=True)
class StepResult:
    ok: bool
    message: str = ""  # what the program reported, for the log
    detail: object = None  # the stage's own result, for the views
    # The file's path after the step, when the step gave the file another one (a remux to a new name).
    moved_to: Path | None = None


class Recovery(StrEnum):
    """What a stage makes of a step that was running when the app stopped."""

    # Read the file again: done when the plan comes out unchanged, run again when it is as planned.
    RECHECK = "recheck"
    REDO = "redo"  # the file is as planned; run the step again
    SETTLED = "settled"  # the stage finished or failed the step itself, see `Resumed.result`
    STALE = "stale"  # the files match no point of the step; nothing is touched


@dataclass(frozen=True, slots=True)
class Resumed:
    recovery: Recovery
    result: StepResult | None = None  # for SETTLED


class Stage(Protocol):
    """One stage of the pipeline. Its options are `profile.for_stage(id)`; it plans changes only where they ask
    for one.

    `plan` reads nothing from disk and writes nothing. `apply` is called only with a plan whose `writes` is set,
    and only from a background thread; `progress`, when given, takes the fraction done. `resume` is asked about a
    step that was running when the app stopped, with the file's stamp at preview. The fields of a stage are its
    settings for the batch (program paths, the batch's source), so its `repr` is part of the options stamp of a
    preview.
    """

    id: ClassVar[str]
    remuxes: ClassVar[bool]  # writes a new file, so it can carry out a plan that needs a remux

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan: ...

    def apply(
        self, plan: StagePlan, cancel: threading.Event | None, progress: StepProgress | None = None
    ) -> StepResult: ...

    def resume(self, plan: StagePlan, before: FileStamp, cancel: threading.Event | None) -> Resumed: ...


RECHECK = Resumed(Recovery.RECHECK)
# The message of a metadata step whose edits the file does not show when read back: "missed: <missed>/<planned>".
MISSED = "missed"
# The message of a subtitle step whose engine is missing at Apply: "not-available: <phase>", the phase being a step
# kind, `reference_phase` for the reference, or "approval". The plan leaves out work no engine can do, so this is said
# only when an engine went missing between the plan and the run.
NOT_AVAILABLE = "not-available"
APPROVAL = StepKind.APPROVAL.value
# The engines that need no program, by the kind of work they do; an engine registers here. The pipeline adds the ones
# that need a program it found (`reading_runners`), and its stages plan only the work these can do, so a missing engine
# leaves its subtitles out and nothing else.
# Translation needs no program but a server that answers, which the plans check as the `AI` kind of work.
RUNNERS: dict[StepKind, Runner] = {
    StepKind.CLEAN: clean_runner(RULES.book),
    StepKind.TRANSLATE: translate_runner(lambda: AI.backend, RULES.book),
}
# The Jobs phases of a file's subtitle step in the order they run; a file shows the ones its plan holds. "beside"
# writes the subtitles that go beside the video, once their work is done.
SUBTITLE_PHASES = ("reference", "ocr", "read", "translate", "clean", "sync", "resplit", "approval", "beside")


@dataclass(frozen=True, slots=True)
class CleanupSets:
    """The cleanup rule sets that exist, for the plans to choose from. A stage holds them like its other settings: they
    are part of the stamp of a preview through `stamp`, which names each set by its rules' fingerprint, so a rule
    that changes makes the preview out of date."""

    sets: Mapping[str, RuleSet] = field(default_factory=dict, repr=False)
    stamp: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stamp", "|".join(f"{name}:{found.fingerprint}" for name, found in self.sets.items()))


def available(runners: Mapping[StepKind, Runner]) -> tuple[StepKind, ...]:
    """The kinds of work `runners` can do, in the order they run."""
    return tuple(kind for kind in StepKind if kind in runners)


def reference_phase(step: Step) -> str:
    """How a reference read is named in a step's message and the drawer: apart from reading a track to clean it."""
    return "ocr" if step.kind is StepKind.OCR else "reference"


def subtitle_phases(plan: SubtitlePlan) -> tuple[str, ...]:
    """The phases of a file's subtitle step: reading its reference, each kind of work its finished subtitles take,
    then the approval when the file waits for one."""
    held = {step.kind.value for finished in plan.finished for step in finished.steps}
    if plan.reference is not None and plan.reference.step is not None:
        held.add(reference_phase(plan.reference.step))
    if plan.reference is not None and plan.reference.sync is not None:
        held.add(StepKind.SYNC.value)
    if plan.waits:
        held.add(APPROVAL)
    if plan.written:
        held.add("beside")
    return tuple(name for name in SUBTITLE_PHASES if name in held)


@lru_cache(maxsize=8)
def _models(tesseract: Path, folder_time: int | None) -> tuple[str, ...] | None:
    found = installed_languages(tesseract)
    return None if found is None else tuple(sorted(found))


def ocr_languages(tesseract: Path | None) -> tuple[str, ...] | None:
    """The Tesseract models installed, sorted, or None where OCR is not asked for or cannot say. Kept for as long as
    the folder of the models beside the program is as it was, so adding a model is seen without a restart. The first
    call runs the program, which takes a moment."""
    if tesseract is None:
        return None
    try:
        changed = (tesseract.parent / "tessdata").stat().st_mtime_ns
    except OSError:
        changed = None
    return _models(tesseract, changed)


def reading_runners(
    mkvextract: Path | None, tesseract: Path | None, book: Callable[[], RuleBook] | None = None
) -> dict[StepKind, Runner]:
    """The engines that read a subtitle out of the video, for the programs found: a text track needs mkvextract, a
    picture track Tesseract as well. A program that is missing leaves out its engine only."""
    found: dict[StepKind, Runner] = {}
    if mkvextract is not None:
        found[StepKind.READ] = read_runner(mkvextract)
        if tesseract is not None:
            found[StepKind.OCR] = ocr_runner(mkvextract, tesseract, book or RULES.book)
    return found


def sync_runners(ffmpeg: Path | None) -> tuple[dict[StepKind, Runner], SyncSupport]:
    """The sync engine that can run and the support it gives the plans: one runner for the step, which picks the engine
    the step names. An engine whose library is not installed is left out, and one that works against the audio needs
    ffmpeg, so without it only a subtitle reference can be synced."""
    adapters: dict[str, SyncAdapter] = {name: engine(ffmpeg) for name, engine in ENGINES.items() if engine.available()}
    if not adapters:
        return {}, ()
    support = tuple(sorted(((SyncEngine(name), found.audio) for name, found in adapters.items()), key=repr))
    return {StepKind.SYNC: sync_runner(adapters)}, support


def _results() -> ResultStore:
    return ResultStore(results_dir())


def subtitle_plan(
    item: MediaItem,
    profile: Profile,
    can_do: Sequence[StepKind],
    cleanup: CleanupSets,
    models: tuple[str, ...] | None = None,
    syncs: SyncSupport | None = None,
    ai: AiModels | None = None,
) -> SubtitlePlan:
    return plan_subtitles(
        item,
        profile.for_stage("subtitles"),
        profile.for_stage("tracks"),
        available=can_do,
        rule_sets=cleanup.sets,
        ocr_languages=models,
        syncs=None if syncs is None else dict(syncs),
        ai=ai,
    )


@dataclass(frozen=True, slots=True)
class TracksStage:
    """Decides which tracks stay and which flags change; it writes nothing itself."""

    id: ClassVar[str] = "tracks"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = plan_tracks(item, profile.for_stage(self.id))
        if isinstance(result, PlanRefused):
            return StagePlan(self.id, PlanState.REFUSED, result)
        changed = (
            result.reordered
            or bool(result.dropped)
            or any(k.external is not None or k.flag_changes for k in result.kept)
        )
        state = PlanState.CHANGES if changed else PlanState.UNCHANGED
        return StagePlan(self.id, state, result, needs_remux=result.needs_remux)

    def apply(
        self, plan: StagePlan, cancel: threading.Event | None, progress: StepProgress | None = None
    ) -> StepResult:
        raise NotImplementedError("track plans never write; Metadata or a remux carries them out")

    def resume(self, plan: StagePlan, before: FileStamp, cancel: threading.Event | None) -> Resumed:
        return RECHECK


@dataclass(frozen=True, slots=True)
class MetadataStage:
    """Header edits through mkvpropedit, checked by reading the file again."""

    mkvpropedit: Path
    programs: Programs  # for the read after the edit
    source: str = ""  # the `{source}` token for the batch
    available: tuple[StepKind, ...] = ()  # the subtitle work that can run, which may ask for a new file
    cleanup: CleanupSets = field(default_factory=CleanupSets)
    models: tuple[str, ...] | None = None  # the Tesseract models installed, sorted; None leaves them unchecked
    syncs: SyncSupport | None = None  # the sync engines that can run; None leaves them unchecked
    ai: AiModels | None = None  # the AI models, while a server answers

    id: ClassVar[str] = "metadata"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = plan_metadata(
            item,
            profile.for_stage(self.id),
            profile.for_stage("naming"),
            profile.for_stage("tracks"),
            source=self.source,
            remux=bool(
                subtitle_plan(item, profile, self.available, self.cleanup, self.models, self.syncs, self.ai).into_video
            ),
        )
        if isinstance(result, MetadataRefused):
            return StagePlan(self.id, PlanState.REFUSED, result)
        state = PlanState.CHANGES if result.changes else PlanState.UNCHANGED
        writes = bool(result.changes) and not result.needs_remux
        return StagePlan(self.id, state, result, writes=writes, needs_remux=result.needs_remux)

    def apply(
        self, plan: StagePlan, cancel: threading.Event | None, progress: StepProgress | None = None
    ) -> StepResult:
        if not isinstance(plan.plan, MetadataPlan):
            raise TypeError(f"not a metadata plan: {type(plan.plan).__name__}")
        result = apply_metadata(plan.plan, self.mkvpropedit, self.programs, cancel=cancel)
        missed = f"{MISSED}: {len(result.missed)}/{len(plan.plan.changes)}"
        return StepResult(result.ok, result.error or (missed if result.missed else ""), result)

    def resume(self, plan: StagePlan, before: FileStamp, cancel: threading.Event | None) -> Resumed:
        return RECHECK


@dataclass(frozen=True, slots=True)
class MuxStage:
    """A new file through mkvmerge for a video whose track plan needs one, checked before the original goes."""

    mkvmerge: Path
    programs: Programs  # for the read that checks the new file
    source: str = ""  # the `{source}` token, for the names Metadata gives
    results: ResultStore = field(default_factory=_results)  # where the finished subtitles it adds are kept
    available: tuple[StepKind, ...] = ()  # the subtitle work that can run, whose results it adds
    cleanup: CleanupSets = field(default_factory=CleanupSets)
    models: tuple[str, ...] | None = None  # the Tesseract models installed, sorted; None leaves them unchecked
    syncs: SyncSupport | None = None  # the sync engines that can run; None leaves them unchecked
    ai: AiModels | None = None  # the AI models, while a server answers
    # Not a setting of the batch, so not part of the stamp; tests put a stand-in for the shell here.
    recycle: Callable[[Sequence[Path]], None] = field(default=recycle, repr=False, compare=False)

    id: ClassVar[str] = "mux"
    remuxes: ClassVar[bool] = True

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        subtitles = subtitle_plan(item, profile, self.available, self.cleanup, self.models, self.syncs, self.ai)
        result = plan_mux(
            item,
            profile.for_stage(self.id),
            profile.for_stage("tracks"),
            profile.for_stage("metadata"),
            profile.for_stage("naming"),
            source=self.source,
            # The subtitles written beside the video stay out of the new file.
            finished=[(finished, self.results.final(subtitles, finished)) for finished in subtitles.into_video],
        )
        if result is None:
            return StagePlan(self.id, PlanState.UNCHANGED)
        if isinstance(result, MuxRefused):
            return StagePlan(self.id, PlanState.REFUSED, result)
        # `needs_remux` too, so Apply counts the file among the remuxed ones.
        return StagePlan(self.id, PlanState.CHANGES, result, writes=True, needs_remux=True)

    def apply(
        self, plan: StagePlan, cancel: threading.Event | None, progress: StepProgress | None = None
    ) -> StepResult:
        if not isinstance(plan.plan, MuxPlan):
            raise TypeError(f"not a mux plan: {type(plan.plan).__name__}")
        result = apply_mux(
            plan.plan, self.mkvmerge, self.programs, recycle=self.recycle, progress=progress, cancel=cancel
        )
        return _mux_step(plan.plan, result)

    def resume(self, plan: StagePlan, before: FileStamp, cancel: threading.Event | None) -> Resumed:
        if not isinstance(plan.plan, MuxPlan):
            return RECHECK
        try:
            unchanged = stamp(plan.plan.source) == before
        except OSError:
            unchanged = False
        result = resume_mux(plan.plan, self.programs, source_unchanged=unchanged, recycle=self.recycle, cancel=cancel)
        if result is None:
            return Resumed(Recovery.REDO)
        if result.failure is Failure.STALE:
            return Resumed(Recovery.STALE)
        return Resumed(Recovery.SETTLED, _mux_step(plan.plan, result))


@dataclass(frozen=True, slots=True)
class SubtitlesStage:
    """The slow subtitle work of a file (reading the reference, translation, cleanup, sync, re-split), each result kept
    for a resume. The finished subtitles then go into the new file through Mux, or, where the place's Output says so,
    are written beside the video by this stage, with no new file for them.

    `runners` carry out the steps, by kind, and say what can run (`available`): a finished subtitle that needs other
    work is left out of the plan, and the file's other changes go on without it."""

    results: ResultStore = field(default_factory=_results)
    runners: Mapping[StepKind, Runner] = field(default_factory=dict, repr=False, compare=False)
    cleanup: CleanupSets = field(default_factory=CleanupSets)
    models: tuple[str, ...] | None = None  # the Tesseract models installed, sorted; None leaves them unchecked
    syncs: SyncSupport | None = None  # the sync engines that can run; None leaves them unchecked
    # The AI models while a server answers; None while none does, which makes AI work unavailable.
    ai: AiModels | None = None
    # Not a setting of the batch, so not part of the stamp; tests put a stand-in for the shell here.
    recycle: Callable[[Sequence[Path]], None] = field(default=recycle, repr=False, compare=False)
    # The OCR program, whose model is part of the name a reference read by OCR is kept under; it does not change a plan.
    tesseract: Path | None = field(default=None, repr=False, compare=False)
    # Part of the stamp of a preview, unlike the runners themselves: what can run decides the plan.
    available: tuple[StepKind, ...] = field(init=False)

    def __post_init__(self) -> None:
        server = {StepKind.AI: None} if self.ai is not None else {}
        object.__setattr__(self, "available", available({**self.runners, **server}))

    id: ClassVar[str] = "subtitles"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = subtitle_plan(item, profile, self.available, self.cleanup, self.models, self.syncs, self.ai)
        if result.finished:
            return StagePlan(self.id, PlanState.CHANGES, result, writes=True, needs_remux=bool(result.into_video))
        return StagePlan(self.id, PlanState.REFUSED if result.cannot else PlanState.UNCHANGED, result)

    def apply(
        self, plan: StagePlan, cancel: threading.Event | None, progress: StepProgress | None = None
    ) -> StepResult:
        """The detail of a finished step is how many results were reused from an earlier run; no view shows it
        yet. The subtitles written beside the video are written last, once all the work of the file is done."""
        work = plan.plan
        if not isinstance(work, SubtitlePlan):
            raise TypeError(f"not a subtitle plan: {type(work).__name__}")
        store = self.results
        store.prune()
        phases = subtitle_phases(work)
        # The steps of each phase, so a phase reports how far through its own steps it is.
        steps_in: Counter[str] = Counter(step.kind.value for finished in work.finished for step in finished.steps)
        if work.reference is not None and work.reference.step is not None:
            steps_in[reference_phase(work.reference.step)] += 1
        if work.reference is not None and work.reference.sync is not None:
            steps_in[StepKind.SYNC.value] += 1
        steps_in["beside"] = int(bool(work.written))
        count = {"reused": 0}
        done_in: Counter[str] = Counter()
        furthest = [0.0]

        def report(phase: str, fraction: float) -> None:
            """The fraction of the step over its phases. Finished subtitles run one after the other, each through its
            own phases, so a later one can be in an earlier phase: the fraction never goes back, and the phase shown is
            the furthest one reached."""
            if progress is not None and phase in phases:
                within = (done_in[phase] + fraction) / steps_in[phase]
                furthest[0] = max(furthest[0], min((phases.index(phase) + within) / len(phases), 1.0))
                progress(furthest[0])

        def run(given: StepWork, inputs: Sequence[Path], phase: str) -> str:
            """Reuse or run one step; the message of a step that cannot run, empty otherwise."""
            if store.kept(given.output, inputs):
                count["reused"] += 1
            else:
                runner = self.runners.get(given.step.kind)
                if runner is None:
                    return f"{NOT_AVAILABLE}: {phase}"
                given.output.parent.mkdir(parents=True, exist_ok=True)
                runner(replace(given, progress=lambda fraction: report(phase, fraction)), cancel)
                # A translation where windows fell back is not kept, so the next run asks for those windows again.
                if not _fell_back(given):
                    store.keep(given.output, inputs)
            report(phase, 1.0)
            done_in[phase] += 1
            return ""

        reference: Path | None = None
        language = work.reference.track.language if work.reference and work.reference.track else None
        if work.reference is not None and (step := work.reference.step) is not None:
            reference = store.reference(work, self._ocr_rules(language) if step.kind is StepKind.OCR else "")
            track = work.reference.track
            given = StepWork(step, work.video, None, None, track.language if track else None, track, reference)
            if failed := run(given, [work.video], reference_phase(step)):
                return StepResult(False, failed)
        elif work.reference is not None and (paired := work.reference.paired) is not None:
            reference = store.reference(work)
            # Stamped with the file, so a reference changed on disk is read again and the work against it runs again.
            # A file that cannot be read fails the step with its own error, as a step's engine does.
            if not store.kept(reference, [paired.path]):
                cues = read_cues(paired.path, language)
                reference.parent.mkdir(parents=True, exist_ok=True)
                write_cues(reference, cues, language=language)
                store.keep(reference, [paired.path])
            if (sync := work.reference.sync) is not None:
                # Synced to the audio (no reference given), kept apart by the sync's engine and settings.
                synced = store.reference(work, repr(sync))
                given = StepWork(sync, work.video, reference, None, language, None, synced)
                if failed := run(given, [work.video, reference], StepKind.SYNC.value):
                    return StepResult(False, failed)
                reference = synced
        settled: set[int] = set()
        for number, finished in enumerate(work.finished):
            # Its original is in the Recycle Bin, so the steps made of it cannot run again; the checked copy is the
            # result.
            if finished.replaces and finished.target is not None and finish_replace(finished.target):
                settled.add(number)
                continue
            source = finished.paired.path if finished.paired is not None else None
            for index, step in enumerate(finished.steps):
                output = store.output(work, finished, index)
                inputs = [work.video, *([source] if source else []), *([reference] if reference else [])]
                given = StepWork(
                    step, work.video, source, reference, finished.language, finished.track, output, language
                )
                if failed := run(given, inputs, step.kind.value):
                    return StepResult(False, failed)
                source = output
        # Nothing approves in this version: a plan waits only where approval is registered as available.
        if work.waits:
            return StepResult(False, f"{NOT_AVAILABLE}: {APPROVAL}")
        for number, finished in enumerate(work.finished):
            if finished.target is None or number in settled:
                continue
            result = store.final(work, finished)
            # A new file beside a subtitle that came out as it went in (already in sync, nothing to clean) would only
            # copy it: no change was asked for, so no file is written. A replacement of it is left as it is anyway.
            if finished.paired is not None and reads_as_original(result, finished.paired.path, finished.language):
                continue
            try:
                write_beside(
                    result,
                    finished.target,
                    finished.language,
                    replaces=finished.replaces,
                    recycle=self.recycle,
                )
            except BesideError as error:
                return StepResult(False, str(error))
            except OSError as error:
                return StepResult(False, f"{BesideFailure.WRITE.value}: {error}")
        report("beside", 1.0)
        return StepResult(True, detail=count["reused"])

    def _ocr_rules(self, language: Language | None) -> str:
        """The fingerprint of how a reference in `language` is read by OCR: the way the pictures are read, the model
        Tesseract reads them with and the OCR fixes."""
        sets = self.cleanup.sets
        model = model_stamp(self.tesseract, language) if self.tesseract is not None else ""
        fixes = (f"{name}:{sets[name].fingerprint}" for name in (OCR_SET, OCR_EXTRA) if name in sets)
        return "+".join([READING, model, *fixes])

    def resume(self, plan: StagePlan, before: FileStamp, cancel: threading.Event | None) -> Resumed:
        # The kept results tell what is done, so running the step again repeats only what was not; a subtitle already
        # written beside the video reads as its result and is left as it is.
        return Resumed(Recovery.REDO)


def _fell_back(work: StepWork) -> bool:
    return (
        work.step.kind is StepKind.TRANSLATE and (found := read_report(work.output)) is not None and found.needs_review
    )


def _mux_step(plan: MuxPlan, result: MuxResult) -> StepResult:
    message = "" if result.ok else f"{result.failure}: {result.detail}".rstrip(": ")
    moved = plan.output if result.ok and plan.output != plan.source else None
    return StepResult(result.ok, message, result, moved)


def renamed_to(plan: StagePlan) -> Path | None:
    """The new name a finished step gave its file, from the stored plan: a run that resumes a job does not hold the
    result of the steps an earlier run finished."""
    mux = plan.plan
    return mux.output if isinstance(mux, MuxPlan) and mux.output != mux.source else None


def pipeline(
    programs: Programs,
    mkvpropedit: Path | None,
    *,
    source: str = "",
    results: ResultStore | None = None,
    runners: Mapping[StepKind, Runner] | None = None,
    cleanup: CleanupSets | None = None,
    tesseract: Path | None = None,
    ffmpeg: Path | None = None,
    ai: AiModels | None = None,
) -> tuple[Stage, ...]:
    """The stages in the order they run. A stage whose program is missing is left out, so its features are off
    and nothing else; a new stage is one more entry here. On a file Mux remuxes it writes the header as well and
    Metadata writes nothing, so Mux is that file's only writing step. Subtitles needs no program of its own: the work
    of an engine that is missing (`runners`, by default `RUNNERS` and the readers of the programs found) is left out,
    and without mkvmerge its work needs a new file that cannot be written. `cleanup` are the rule sets plans may
    choose from, the user's rule store's by default. `tesseract` is the OCR program, and with it the models it has
    decide which picture tracks can be read. `ffmpeg` is what syncing against the audio needs. `ai` are the AI models
    while a server answers; without them AI work is left out."""
    results = results or _results()
    cleanup = cleanup or CleanupSets(RULES.book().sets)
    models = ocr_languages(tesseract) if runners is None else None
    sync, syncs = sync_runners(ffmpeg) if runners is None else ({}, None)
    engines = {**RUNNERS, **reading_runners(programs.mkvextract, tesseract), **sync} if runners is None else runners
    subtitles = SubtitlesStage(results, engines, cleanup, models, syncs, ai, tesseract=tesseract)
    stages: list[Stage] = [TracksStage(), subtitles]
    if programs.mkvmerge is not None:
        mux = MuxStage(programs.mkvmerge, programs, source, results, subtitles.available, cleanup, models, syncs, ai)
        stages.append(mux)
    if mkvpropedit is not None:
        stages.append(MetadataStage(mkvpropedit, programs, source, subtitles.available, cleanup, models, syncs, ai))
    return tuple(stages)
