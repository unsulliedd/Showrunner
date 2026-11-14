"""The shape every stage has for the job queue: plan one file, apply one plan. The stage engines stay as they are;
the classes here only adapt them."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol

from showrunner.app.profiles.profile import Profile
from showrunner.core.media import MediaItem
from showrunner.stages.metadata import MetadataPlan, MetadataRefused, apply_metadata, plan_metadata
from showrunner.stages.tracks import PlanRefused, plan_tracks
from showrunner.tools.probe import Programs


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


class Stage(Protocol):
    """One stage of the pipeline. Its options are `profile.for_stage(id)`, and their `enabled` is its switch.

    `plan` reads nothing from disk and writes nothing. `apply` is called only with a plan whose `writes` is set,
    and only from a background thread. The fields of a stage are its settings for the batch (program paths, the
    batch's source), so its `repr` is part of the options stamp of a preview.
    """

    id: ClassVar[str]
    remuxes: ClassVar[bool]  # writes a new file, so it can carry out a plan that needs a remux

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan: ...

    def apply(self, plan: StagePlan, cancel: threading.Event | None) -> StepResult: ...


@dataclass(frozen=True, slots=True)
class TracksStage:
    """Decides which tracks stay and which flags change; it writes nothing itself."""

    id: ClassVar[str] = "tracks"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        result = plan_tracks(item, profile.for_stage(self.id))
        if isinstance(result, PlanRefused):
            return StagePlan(self.id, PlanState.REFUSED, result)
        changed = bool(result.dropped) or any(k.external is not None or k.flag_changes for k in result.kept)
        state = PlanState.CHANGES if changed else PlanState.UNCHANGED
        return StagePlan(self.id, state, result, needs_remux=result.needs_remux)

    def apply(self, plan: StagePlan, cancel: threading.Event | None) -> StepResult:
        raise NotImplementedError("track plans never write; Metadata or a remux carries them out")


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

    def apply(self, plan: StagePlan, cancel: threading.Event | None) -> StepResult:
        if not isinstance(plan.plan, MetadataPlan):
            raise TypeError(f"not a metadata plan: {type(plan.plan).__name__}")
        result = apply_metadata(plan.plan, self.mkvpropedit, self.programs, cancel=cancel)
        missed = f"{len(result.missed)} of {len(plan.plan.changes)} changes not found after the edit"
        return StepResult(result.ok, result.error or (missed if result.missed else ""), result)


def pipeline(programs: Programs, mkvpropedit: Path | None, *, source: str = "") -> tuple[Stage, ...]:
    """The stages in the order they run. A stage whose program is missing is left out, so its features are off
    and nothing else; a new stage is one more entry here."""
    stages: list[Stage] = [TracksStage()]
    if mkvpropedit is not None:
        stages.append(MetadataStage(mkvpropedit, programs, source))
    return tuple(stages)
