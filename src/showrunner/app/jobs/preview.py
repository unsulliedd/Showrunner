"""Preview: every stage planned for each file of a batch, with the stamps that tell whether the preview still holds.
Files are read for their stamp only; nothing is written."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from showrunner.app.jobs.blocked import blocked_stages
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
    options_key: str = ""  # of the options this file was planned with; see `options_key`

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
    # See `options_key`; for a preview of one profile per file (`preview_each`), a digest of each file's key.
    options_key: str
    # By options key, the options the plans were made with: the left-out groups and the blocked stages ask for
    # nothing in them, as they did for planning. A job stores them, so a resumed step is planned again with the same
    # options.
    profiles: dict[str, Profile]
    files: tuple[FilePreview, ...]

    def is_current(
        self,
        profile: Profile | Mapping[Path, Profile],
        stages: Sequence[Stage],
        blocked: Collection[str] = (),
        left_out: Collection[ChangeGroup] = (),
    ) -> bool:
        """Whether the preview was made with these options. With one profile per file, each file's blocked stages
        are its options' own, as `preview_each` plans them, and `blocked` is not read."""
        if isinstance(profile, Profile):
            return options_key(profile, stages, blocked, left_out) == self.options_key
        if {f.item.file.path for f in self.files} - profile.keys():
            return False
        keys = _keys(profile, stages, left_out)
        return _each_key(self.files, lambda f: keys[id(profile[f.item.file.path])]) == self.options_key


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
    return Preview(key, {key: planning}, files)


def preview_each(
    items: Sequence[MediaItem],
    profiles: Mapping[Path, Profile],
    stages: Sequence[Stage],
    *,
    left_out: Collection[ChangeGroup] = (),
    finished: Finished | None = None,
    stamped: bool = True,
) -> Preview:
    """`preview` with each file's own options, `profiles` by path. The stages a file's options block are blocked for
    that file (`blocked_stages`). Files given the same options object are planned together, so the files of a season
    that set nothing of their own cost one options key, not one each; the files keep the order of `items`."""
    ids = {s.id for s in stages}
    groups: dict[int, tuple[Profile, list[MediaItem]]] = {}
    for item in items:
        profile = profiles[item.file.path]
        groups.setdefault(id(profile), (profile, []))[1].append(item)
    parts = [
        preview(
            group,
            profile,
            stages,
            blocked=set(blocked_stages(profile)) & ids,
            left_out=left_out,
            finished=finished,
            stamped=stamped,
        )
        for profile, group in groups.values()
    ]
    planned = {f.item.file.path: f for part in parts for f in part.files}
    files = tuple(planned[item.file.path] for item in items)
    used = {key: profile for part in parts for key, profile in part.profiles.items()}
    return Preview(_each_key(files, lambda f: f.options_key), used, files)


def _keys(
    profiles: Mapping[Path, Profile], stages: Sequence[Stage], left_out: Collection[ChangeGroup]
) -> dict[int, str]:
    """The options key of each options object in `profiles`, computed once per object."""
    ids = {s.id for s in stages}
    unique = {id(profile): profile for profile in profiles.values()}
    return {
        n: options_key(profile, stages, set(blocked_stages(profile)) & ids, left_out) for n, profile in unique.items()
    }


def _each_key(files: Iterable[FilePreview], key_of: Callable[[FilePreview], str]) -> str:
    data = [[str(f.item.file.path), key_of(f)] for f in files]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


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
            return FilePreview(item, None, (), FileOutcome.MISSING, str(error), options_key=key)
    before = current is not None and finished is not None and finished(current.content_hash, key)
    plans = tuple(StagePlan(s.id, PlanState.BLOCKED) if s.id in blocked else s.plan(item, profile) for s in stages)
    return FilePreview(item, current, plans, _outcome(plans, can_remux), finished_before=before, options_key=key)


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
