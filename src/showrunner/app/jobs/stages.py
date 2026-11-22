"""The shape every stage has for the job queue: plan one file, apply one plan. The stage engines stay as they are;
the classes here only adapt them."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from showrunner.app.jobs.hashing import FileStamp, stamp
from showrunner.app.jobs.results import ResultStore
from showrunner.app.profiles.profile import Profile
from showrunner.app.rules import RULES
from showrunner.app.storage.paths import results_dir
from showrunner.core.media import MediaItem
from showrunner.stages.metadata import MetadataPlan, MetadataRefused, apply_metadata, plan_metadata
from showrunner.stages.mux import Failure, MuxPlan, MuxRefused, MuxResult, apply_mux, plan_mux, resume_mux
from showrunner.stages.subtitles import Step, StepKind, SubtitlePlan, plan_subtitles
from showrunner.stages.subtitles.clean import clean_runner
from showrunner.stages.subtitles.work import Runner, StepWork
from showrunner.stages.tracks import PlanRefused, plan_tracks
from showrunner.tools.cleanit import RuleSet
from showrunner.tools.probe import Programs
from showrunner.tools.recycle import recycle

StepProgress = Callable[[float], None]  # the fraction of the step done, from 0 to 1


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
# The engines this version has, by the kind of work they do; an engine registers here. The pipeline's stages plan only
# the work these can do, so a missing engine leaves its subtitles out and nothing else.
RUNNERS: dict[StepKind, Runner] = {StepKind.CLEAN: clean_runner(RULES.book)}


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


def _results() -> ResultStore:
    return ResultStore(results_dir())


def subtitle_plan(item: MediaItem, profile: Profile, can_do: Sequence[StepKind], cleanup: CleanupSets) -> SubtitlePlan:
    return plan_subtitles(
        item, profile.for_stage("subtitles"), profile.for_stage("tracks"), available=can_do, rule_sets=cleanup.sets
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

    id: ClassVar[str] = "metadata"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = plan_metadata(
            item,
            profile.for_stage(self.id),
            profile.for_stage("naming"),
            profile.for_stage("tracks"),
            source=self.source,
            remux=bool(subtitle_plan(item, profile, self.available, self.cleanup).finished),
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
    # Not a setting of the batch, so not part of the stamp; tests put a stand-in for the shell here.
    recycle: Callable[[Sequence[Path]], None] = field(default=recycle, repr=False, compare=False)

    id: ClassVar[str] = "mux"
    remuxes: ClassVar[bool] = True

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        subtitles = subtitle_plan(item, profile, self.available, self.cleanup)
        result = plan_mux(
            item,
            profile.for_stage(self.id),
            profile.for_stage("tracks"),
            profile.for_stage("metadata"),
            profile.for_stage("naming"),
            source=self.source,
            finished=[(finished, self.results.final(subtitles, finished)) for finished in subtitles.finished],
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
    for a resume; the finished subtitles then go into the new file through Mux. It writes nothing beside the video.

    `runners` carry out the steps, by kind, and say what can run (`available`): a finished subtitle that needs other
    work is left out of the plan, and the file's other changes go on without it."""

    results: ResultStore = field(default_factory=_results)
    runners: Mapping[StepKind, Runner] = field(default_factory=dict, repr=False, compare=False)
    cleanup: CleanupSets = field(default_factory=CleanupSets)
    # Part of the stamp of a preview, unlike the runners themselves: what can run decides the plan.
    available: tuple[StepKind, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "available", available(self.runners))

    id: ClassVar[str] = "subtitles"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = subtitle_plan(item, profile, self.available, self.cleanup)
        if result.finished:
            return StagePlan(self.id, PlanState.CHANGES, result, writes=True, needs_remux=True)
        return StagePlan(self.id, PlanState.REFUSED if result.cannot else PlanState.UNCHANGED, result)

    def apply(
        self, plan: StagePlan, cancel: threading.Event | None, progress: StepProgress | None = None
    ) -> StepResult:
        """The detail of a finished step is how many results were reused from an earlier run; no view shows it
        yet."""
        work = plan.plan
        if not isinstance(work, SubtitlePlan):
            raise TypeError(f"not a subtitle plan: {type(work).__name__}")
        store = self.results
        store.prune()
        total = sum(len(finished.steps) for finished in work.finished) + 1
        count = {"done": 0, "reused": 0}

        def run(given: StepWork, inputs: Sequence[Path], phase: str) -> str:
            """Reuse or run one step; the message of a step that cannot run, empty otherwise."""
            count["done"] += 1
            if store.kept(given.output, inputs):
                count["reused"] += 1
                return ""
            runner = self.runners.get(given.step.kind)
            if runner is None:
                return f"{NOT_AVAILABLE}: {phase}"
            given.output.parent.mkdir(parents=True, exist_ok=True)
            runner(given, cancel)
            store.keep(given.output, inputs)
            if progress is not None:
                progress(count["done"] / total)
            return ""

        reference: Path | None = None
        if work.reference is not None and (step := work.reference.step) is not None:
            reference = store.reference(work)
            track = work.reference.track
            given = StepWork(step, work.video, None, None, track.language if track else None, track, reference)
            if failed := run(given, [work.video], reference_phase(step)):
                return StepResult(False, failed)
        for finished in work.finished:
            source = finished.paired.path if finished.paired is not None else None
            for index, step in enumerate(finished.steps):
                output = store.output(work, finished, index)
                inputs = [work.video, *([source] if source else []), *([reference] if reference else [])]
                given = StepWork(step, work.video, source, reference, finished.language, finished.track, output)
                if failed := run(given, inputs, step.kind.value):
                    return StepResult(False, failed)
                source = output
        # Nothing approves in this version: a plan waits only where approval is registered as available.
        if work.waits:
            return StepResult(False, f"{NOT_AVAILABLE}: {APPROVAL}")
        return StepResult(True, detail=count["reused"])

    def resume(self, plan: StagePlan, before: FileStamp, cancel: threading.Event | None) -> Resumed:
        # The kept results tell what is done, so running the step again repeats only what was not.
        return Resumed(Recovery.REDO)


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
) -> tuple[Stage, ...]:
    """The stages in the order they run. A stage whose program is missing is left out, so its features are off
    and nothing else; a new stage is one more entry here. On a file Mux remuxes it writes the header as well and
    Metadata writes nothing, so Mux is that file's only writing step. Subtitles needs no program of its own: the work
    of an engine that is missing (`runners`, `RUNNERS` by default) is left out, and without mkvmerge its work needs a
    new file that cannot be written. `cleanup` are the rule sets plans may choose from, the user's rule store's by
    default."""
    results = results or _results()
    cleanup = cleanup or CleanupSets(RULES.book().sets)
    subtitles = SubtitlesStage(results, RUNNERS if runners is None else runners, cleanup)
    stages: list[Stage] = [TracksStage(), subtitles]
    if programs.mkvmerge is not None:
        stages.append(MuxStage(programs.mkvmerge, programs, source, results, subtitles.available, cleanup))
    if mkvpropedit is not None:
        stages.append(MetadataStage(mkvpropedit, programs, source, subtitles.available, cleanup))
    return tuple(stages)
