"""The shape every stage has for the job queue: plan one file, apply one plan. The stage engines stay as they are;
the classes here only adapt them."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from showrunner.app.jobs.hashing import FileStamp, stamp
from showrunner.app.profiles.profile import Profile
from showrunner.core.media import MediaItem
from showrunner.stages.metadata import MetadataPlan, MetadataRefused, apply_metadata, plan_metadata
from showrunner.stages.mux import Failure, MuxPlan, MuxRefused, MuxResult, apply_mux, plan_mux, resume_mux
from showrunner.stages.tracks import PlanRefused, plan_tracks
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

    id: ClassVar[str] = "metadata"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = plan_metadata(
            item,
            profile.for_stage(self.id),
            profile.for_stage("naming"),
            profile.for_stage("tracks"),
            source=self.source,
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
        missed = f"{len(result.missed)} of {len(plan.plan.changes)} changes not found after the edit"
        return StepResult(result.ok, result.error or (missed if result.missed else ""), result)

    def resume(self, plan: StagePlan, before: FileStamp, cancel: threading.Event | None) -> Resumed:
        return RECHECK


@dataclass(frozen=True, slots=True)
class MuxStage:
    """A new file through mkvmerge for a video whose track plan needs one, checked before the original goes."""

    mkvmerge: Path
    programs: Programs  # for the read that checks the new file
    source: str = ""  # the `{source}` token, for the names Metadata gives
    # Not a setting of the batch, so not part of the stamp; tests put a stand-in for the shell here.
    recycle: Callable[[Sequence[Path]], None] = field(default=recycle, repr=False, compare=False)

    id: ClassVar[str] = "mux"
    remuxes: ClassVar[bool] = True

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = plan_mux(
            item,
            profile.for_stage(self.id),
            profile.for_stage("tracks"),
            profile.for_stage("metadata"),
            profile.for_stage("naming"),
            source=self.source,
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


def _mux_step(plan: MuxPlan, result: MuxResult) -> StepResult:
    message = "" if result.ok else f"{result.failure}: {result.detail}".rstrip(": ")
    moved = plan.output if result.ok and plan.output != plan.source else None
    return StepResult(result.ok, message, result, moved)


def renamed_to(plan: StagePlan) -> Path | None:
    """The new name a finished step gave its file, from the stored plan: a run that resumes a job does not hold the
    result of the steps an earlier run finished."""
    mux = plan.plan
    return mux.output if isinstance(mux, MuxPlan) and mux.output != mux.source else None


def pipeline(programs: Programs, mkvpropedit: Path | None, *, source: str = "") -> tuple[Stage, ...]:
    """The stages in the order they run. A stage whose program is missing is left out, so its features are off
    and nothing else; a new stage is one more entry here. On a file Mux remuxes it writes the header as well and
    Metadata writes nothing, so Mux is that file's only writing step."""
    stages: list[Stage] = [TracksStage()]
    if programs.mkvmerge is not None:
        stages.append(MuxStage(programs.mkvmerge, programs, source))
    if mkvpropedit is not None:
        stages.append(MetadataStage(mkvpropedit, programs, source))
    return tuple(stages)
