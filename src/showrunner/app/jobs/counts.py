"""How many changes a file's plans make, per group of planned change (the top bar and Apply) and per workspace tab
(the numbers on the tabs).

A change is one edit to one file. Tracks and new files: the new file, its track order, and each flag (default,
forced) that moves to other tracks of a kind. Names and flags: the title, each track's name and language, and each
flag a name implies. A tab counts only what it shows: Names the titles and track names, Tracks everything else.
"""

from __future__ import annotations

from collections.abc import Iterable

from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import FilePreview
from showrunner.core.track import Track, TrackFlags, TrackKind
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.tracks import Flag, TrackPlan
from showrunner.tools.mkvtoolnix.propedit import Property

_FLAG_PROPERTY = {Flag.DEFAULT: Property.FLAG_DEFAULT, Flag.FORCED: Property.FLAG_FORCED}


def track_changes(plan: TrackPlan) -> int:
    """1 for a new file, 1 for a new track order, plus 1 for each flag and kind whose tracks change: the default
    audio moving from English to Turkish is one change, not one per track."""
    before = [(d.track, d.track.flags) for d in plan.dropped if d.external is None]
    before += [(k.track, k.track.flags) for k in plan.kept]
    had, has = _flagged(before), _flagged((k.track, k.flags) for k in plan.kept)
    return int(plan.needs_remux) + int(plan.reordered) + sum(had.get(key) != has.get(key) for key in had.keys() | has)


def _flagged(tracks: Iterable[tuple[Track, TrackFlags]]) -> dict[tuple[Flag, TrackKind], set[int]]:
    """The IDs of the tracks that carry each flag, by flag and kind; a flag no track of a kind carries is absent."""
    found: dict[tuple[Flag, TrackKind], set[int]] = {}
    for track, flags in tracks:
        for flag in Flag:
            if getattr(flags, flag.value):
                found.setdefault((flag, track.kind), set()).add(track.id)
    return found


def ruled_flags(tracks: TrackPlan | None) -> set[tuple[Property, int]]:
    """The flag edits (property and track ID) the track rules move."""
    return {
        (_FLAG_PROPERTY[change.flag], kept.track.id)
        for kept in (tracks.kept if tracks is not None else ())
        for change in kept.flag_changes
    }


def name_parts(plan: MetadataPlan, tracks: TrackPlan | None = None) -> dict[str, int]:
    """Metadata's changes by kind: titles, track names, languages, and the flags a name implies. The flags the track
    rules move are left out: Metadata writes those on a file that is not remuxed, but they belong to the Tracks group.
    A forced flag a name implies is an implied flag."""
    ruled = ruled_flags(tracks)
    found = dict.fromkeys(("titles", "names", "languages", "implied"), 0)
    for change in plan.changes:
        if change.prop is Property.TITLE:
            found["titles"] += 1
        elif change.prop is Property.NAME:
            found["names"] += 1
        elif change.prop is Property.LANGUAGE:
            found["languages"] += 1
        elif (change.prop, change.track_id) not in ruled:
            found["implied"] += 1
    return found


def file_parts(file: FilePreview) -> dict[str, int]:
    """A file's changes by kind: the new file, its track order and the flags the rules move (Tracks and new files),
    then titles, track names, languages and the flags a name implies (Names and flags); a refused or blocked stage
    counts none. Counted once per plan: a refresh reads every file's counts several times, and the next refresh
    reads them again while the plan stays. The result is shared: callers copy it before changing it."""
    held = _counted.get(id(file))
    if held is not None and held[0] is file:
        return held[1]
    stage = file.plan_for("tracks")
    tracks = stage.plan if stage is not None and isinstance(stage.plan, TrackPlan) else None
    found = dict.fromkeys(("new_file", "order", "flags"), 0)
    if tracks is not None:
        found["new_file"] = int(tracks.needs_remux)
        found["order"] = int(tracks.reordered)
        found["flags"] = track_changes(tracks) - found["new_file"] - found["order"]
    metadata = file.plan_for("metadata")
    if metadata is not None and isinstance(metadata.plan, MetadataPlan):
        found.update(name_parts(metadata.plan, tracks))
    else:
        found.update(dict.fromkeys(("titles", "names", "languages", "implied"), 0))
    if len(_counted) >= _COUNTED_LIMIT:
        _counted.clear()
    _counted[id(file)] = (file, found)  # the file is held, so its id is not given to another one while it is here
    return found


_COUNTED_LIMIT = 4096  # files' counts kept; a whole show's two plans are some hundreds
_counted: dict[int, tuple[FilePreview, dict[str, int]]] = {}


def count_changes(file: FilePreview) -> dict[ChangeGroup, int]:
    """The changes of each group in one file's plans; a refused or blocked stage counts none."""
    found = file_parts(file)
    return {
        ChangeGroup.TRACKS: found["new_file"] + found["order"] + found["flags"],
        ChangeGroup.NAMES: found["titles"] + found["names"] + found["languages"] + found["implied"],
    }


def tab_counts(file: FilePreview) -> dict[str, int]:
    """The changes each tab shows in one file: Names the titles and track names, Tracks the rest (the new file, the
    order, flags and languages), whose choices its chips and rules hold."""
    found = file_parts(file)
    names = found["titles"] + found["names"]
    return {"tracks": sum(found.values()) - names, "names": names}


def implied_flags(file: FilePreview) -> int:
    """The flags a name implies that the file's plan writes."""
    return file_parts(file)["implied"]
