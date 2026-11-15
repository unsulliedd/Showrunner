"""Preview: every stage planned for each file of a batch, with the stamps that tell whether the preview still holds.
Files are read for their stamp only; nothing is written."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from showrunner.app.jobs.groups import ChangeGroup, without
from showrunner.app.jobs.hashing import FileStamp, stamp
from showrunner.app.jobs.stages import PlanState, Stage, StagePlan
from showrunner.app.profiles.profile import Profile, profile_to_json
from showrunner.core.media import MediaItem

# (content hash, options key) -> True when a file with that content was finished with those options.
Finished = Callable[[str, str], bool]

# A blocked stage's options are planned as if they asked for nothing, so that no other stage reads them either.
_BLOCKED_GROUP = {"tracks": ChangeGroup.TRACKS, "metadata": ChangeGroup.NAMES}


class FileOutcome(StrEnum):
    """What Apply would do to a file, the worst case first."""

    MISSING = "missing"  # the file could not be read for its stamp
    # A plan needs a new file and no stage can write one (mkvmerge is missing or Mux is blocked): nothing is written.
    NEEDS_REMUX = "needs-remux"
    REFUSED = "refused"  # a stage refused the file; the stages that did plan it still apply
    CHANGES = "changes"
    # A stage planned changes that no stage writes, such as flags the track rules move while mkvpropedit is missing
    # or Metadata is blocked; nothing is written.
    UNWRITTEN = "unwritten"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class FilePreview:
    item: MediaItem
    stamp: FileStamp | None  # None when the file could not be read
    plans: tuple[StagePlan, ...]  # in pipeline order
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
    # The options the plans were made with: the left-out groups and the blocked stages ask for nothing in it, as
    # they did for planning. A job stores it, so a resumed step is planned again with the same options.
    profile: Profile
    files: tuple[FilePreview, ...]

    def is_current(
        self,
        profile: Profile,
        stages: Sequence[Stage],
        blocked: Collection[str] = (),
        left_out: Collection[ChangeGroup] = (),
    ) -> bool:
        return options_key(profile, stages, blocked, left_out) == self.options_key

    def with_files(self, other: Preview) -> Preview:
        """This preview with the files of `other` in place of the ones with the same path; for planning one file
        again. Both must be made with the same options."""
        if other.options_key != self.options_key:
            raise ValueError("the previews were made with different options")
        fresh = {f.item.file.path: f for f in other.files}
        kept = tuple(fresh.pop(f.item.file.path, f) for f in self.files)
        return replace(self, files=kept + tuple(fresh.values()))


def options_key(
    profile: Profile, stages: Sequence[Stage], blocked: Collection[str] = (), left_out: Collection[ChangeGroup] = ()
) -> str:
    """A digest of everything besides the files that decides the plans: the options, the stages with their
    settings, the blocked stages and the groups left out of the run. The profile's name is left out, so renaming it
    changes nothing."""
    data = {
        "options": profile_to_json(profile),
        "stages": [repr(s) for s in stages],
        "blocked": sorted(blocked),
        "left_out": sorted(left_out),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def preview(
    items: Iterable[MediaItem],
    profile: Profile,
    stages: Sequence[Stage],
    *,
    blocked: Collection[str] = (),
    left_out: Collection[ChangeGroup] = (),
    finished: Finished | None = None,
    stamped: bool = True,
) -> Preview:
    """Plan every stage for each item. `blocked` holds the ids of stages whose options have a problem: such a
    stage is planned for no file, and the stages that read its options see them asking for nothing, so a broken
    rule cannot drive another stage's plan. `left_out` holds the groups this run leaves out, planned as if their
    options were empty; Review shows what a left-out group would do from a second preview with every group in.
    Without `stamped` no file is read: the plans are pure, every stamp is None and no file counts as missing or
    finished before, which suits a plan that follows each choice; Apply needs a stamped preview."""
    key = options_key(profile, stages, blocked, left_out)
    # A problem in a group the run leaves out decides nothing, so it blocks nothing.
    blocked = {s for s in blocked if s not in _BLOCKED_GROUP or _BLOCKED_GROUP[s] not in left_out}
    planning = profile
    for group in {*left_out, *(_BLOCKED_GROUP[s] for s in blocked if s in _BLOCKED_GROUP)}:
        planning = without(planning, group)
    can_remux = any(s.remuxes for s in stages if s.id not in blocked)
    files = tuple(_preview_file(item, planning, stages, blocked, can_remux, key, finished, stamped) for item in items)
    return Preview(key, planning, files)


def _preview_file(
    item: MediaItem,
    profile: Profile,
    stages: Sequence[Stage],
    blocked: Collection[str],
    can_remux: bool,
    key: str,
    finished: Finished | None,
    stamped: bool,
) -> FilePreview:
    current = None
    if stamped:
        try:
            current = stamp(item.file.path)
        except OSError as error:
            return FilePreview(item, None, (), FileOutcome.MISSING, str(error))
    before = current is not None and finished is not None and finished(current.content_hash, key)
    plans = tuple(StagePlan(s.id, PlanState.BLOCKED) if s.id in blocked else s.plan(item, profile) for s in stages)
    return FilePreview(item, current, plans, _outcome(plans, can_remux), finished_before=before)


def _outcome(plans: Sequence[StagePlan], can_remux: bool) -> FileOutcome:
    if not can_remux and any(p.needs_remux for p in plans):
        return FileOutcome.NEEDS_REMUX
    if any(p.state is PlanState.REFUSED for p in plans):
        return FileOutcome.REFUSED
    if any(p.writes for p in plans):
        return FileOutcome.CHANGES
    if any(p.state is PlanState.CHANGES for p in plans):
        return FileOutcome.UNWRITTEN
    return FileOutcome.UNCHANGED
