"""Preview: every switched-on stage planned for each file of a batch, with the stamps that tell whether the
preview still holds. Files are read for their stamp only; nothing is written."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from showrunner.app.jobs.hashing import FileStamp, stamp
from showrunner.app.jobs.stages import PlanState, Stage, StagePlan
from showrunner.app.profiles.profile import Profile, profile_to_json
from showrunner.core.media import MediaItem

# (content hash, options key) -> True when a file with that content was finished with those options.
Finished = Callable[[str, str], bool]


class FileOutcome(StrEnum):
    """What Apply would do to a file, the worst case first."""

    MISSING = "missing"  # the file could not be read for its stamp
    NEEDS_REMUX = "needs-remux"  # a plan needs a new file and no stage that writes one is on: nothing is written
    REFUSED = "refused"  # a stage refused the file; the stages that did plan it still apply
    CHANGES = "changes"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class FilePreview:
    item: MediaItem
    stamp: FileStamp | None  # None when the file could not be read
    plans: tuple[StagePlan, ...]  # switched-on stages in pipeline order
    outcome: FileOutcome
    error: str = ""  # why the stamp could not be taken
    # This content was finished before with the same options, under this name or another. The plans are made
    # all the same: a plan can depend on the file's name or pairing, which the content does not show.
    finished_before: bool = False

    def plan_for(self, stage_id: str) -> StagePlan | None:
        return next((plan for plan in self.plans if plan.stage == stage_id), None)

    @property
    def writes(self) -> tuple[StagePlan, ...]:
        """The plans Apply carries out."""
        if self.outcome in (FileOutcome.MISSING, FileOutcome.NEEDS_REMUX):
            return ()
        return tuple(plan for plan in self.plans if plan.writes)


@dataclass(frozen=True, slots=True)
class Preview:
    options_key: str  # see `options_key`
    # The options the plans were made with: blocked stages are switched off in it, as they were for planning.
    profile: Profile
    files: tuple[FilePreview, ...]

    def is_current(self, profile: Profile, stages: Sequence[Stage], blocked: Collection[str] = ()) -> bool:
        return options_key(profile, stages, blocked) == self.options_key

    def with_files(self, other: Preview) -> Preview:
        """This preview with the files of `other` in place of the ones with the same path; for planning one file
        again. Both must be made with the same options."""
        if other.options_key != self.options_key:
            raise ValueError("the previews were made with different options")
        fresh = {f.item.file.path: f for f in other.files}
        kept = tuple(fresh.pop(f.item.file.path, f) for f in self.files)
        return replace(self, files=kept + tuple(fresh.values()))


def options_key(profile: Profile, stages: Sequence[Stage], blocked: Collection[str] = ()) -> str:
    """A digest of everything besides the files that decides the plans: the options, the stages with their
    settings, and the blocked stages. The profile's name is left out, so renaming it changes nothing."""
    data = {"options": profile_to_json(profile), "stages": [repr(s) for s in stages], "blocked": sorted(blocked)}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def preview(
    items: Iterable[MediaItem],
    profile: Profile,
    stages: Sequence[Stage],
    *,
    blocked: Collection[str] = (),
    finished: Finished | None = None,
) -> Preview:
    """Plan every switched-on stage for each item. `blocked` holds the ids of stages whose options have a
    problem: such a stage is planned for no file, and the stages that read its options see it switched off, so a
    broken rule cannot drive another stage's plan."""
    key = options_key(profile, stages, blocked)
    planning = profile
    for stage_id in blocked:
        planning = planning.with_options(stage_id, replace(planning.for_stage(stage_id), enabled=False))
    active = [s for s in stages if profile.for_stage(s.id).enabled]
    can_remux = any(s.remuxes for s in active if s.id not in blocked)
    files = tuple(_preview_file(item, planning, active, blocked, can_remux, key, finished) for item in items)
    return Preview(key, planning, files)


def _preview_file(
    item: MediaItem,
    profile: Profile,
    stages: Sequence[Stage],
    blocked: Collection[str],
    can_remux: bool,
    key: str,
    finished: Finished | None,
) -> FilePreview:
    try:
        current = stamp(item.file.path)
    except OSError as error:
        return FilePreview(item, None, (), FileOutcome.MISSING, str(error))
    before = finished is not None and finished(current.content_hash, key)
    plans = tuple(StagePlan(s.id, PlanState.BLOCKED) if s.id in blocked else s.plan(item, profile) for s in stages)
    return FilePreview(item, current, plans, _outcome(plans, can_remux), finished_before=before)


def _outcome(plans: Sequence[StagePlan], can_remux: bool) -> FileOutcome:
    if not can_remux and any(p.needs_remux for p in plans):
        return FileOutcome.NEEDS_REMUX
    if any(p.state is PlanState.REFUSED for p in plans):
        return FileOutcome.REFUSED
    if any(p.writes for p in plans):
        return FileOutcome.CHANGES
    return FileOutcome.UNCHANGED
