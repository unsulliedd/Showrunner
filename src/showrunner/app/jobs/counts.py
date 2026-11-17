"""How many changes a file's plans make, per group of planned change: the numbers on the workspace tabs, the top bar
and Review.

A change is one edit to one file. Tracks and new files: the new file, its track order, and each flag (default,
forced) that moves to other tracks of a kind. Names and flags: the title, each track's name and language, and each
flag a name implies.
"""

from __future__ import annotations

from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import FilePreview
from showrunner.core.track import TrackKind
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.tracks import Flag, TrackPlan
from showrunner.tools.mkvtoolnix.propedit import Property

_FLAG_PROPERTY = {Flag.DEFAULT: Property.FLAG_DEFAULT, Flag.FORCED: Property.FLAG_FORCED}


def track_changes(plan: TrackPlan) -> int:
    """1 for a new file, 1 for a new track order, plus 1 for each flag and kind whose tracks change: the default
    audio moving from English to Turkish is one change, not one per track."""
    count = int(plan.needs_remux) + int(plan.reordered)
    before = [d.track for d in plan.dropped if d.external is None] + [k.track for k in plan.kept]
    for flag in Flag:
        for kind in TrackKind:
            had = {t.id for t in before if t.kind is kind and getattr(t.flags, flag.value)}
            has = {k.track.id for k in plan.kept if k.track.kind is kind and getattr(k.flags, flag.value)}
            count += had != has
    return count


def name_changes(plan: MetadataPlan, tracks: TrackPlan | None = None) -> int:
    """Every header change except the flags the track rules move: Metadata writes those on a file that is not
    remuxed, but they belong to the Tracks group. A forced flag a name implies is a name change."""
    ruled = {
        (_FLAG_PROPERTY[change.flag], kept.track.id)
        for kept in (tracks.kept if tracks is not None else ())
        for change in kept.flag_changes
    }
    return sum((change.prop, change.track_id) not in ruled for change in plan.changes)


def count_changes(file: FilePreview) -> dict[ChangeGroup, int]:
    """The changes of each group in one file's plans; a refused or blocked stage counts none."""
    stage = file.plan_for("tracks")
    tracks = stage.plan if stage is not None and isinstance(stage.plan, TrackPlan) else None
    metadata = file.plan_for("metadata")
    return {
        ChangeGroup.TRACKS: track_changes(tracks) if tracks is not None else 0,
        ChangeGroup.NAMES: name_changes(metadata.plan, tracks)
        if metadata and isinstance(metadata.plan, MetadataPlan)
        else 0,
    }
