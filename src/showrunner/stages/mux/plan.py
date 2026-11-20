"""The new file one video needs when its track plan drops a track or adds a subtitle file. Pure logic, nothing is
read or written.

The track rules decide which tracks stay, in which order and with which default and forced flags; Metadata
decides the title, names, languages and the flags names imply. A remux writes both, so the header is never edited
separately on a file that is remuxed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.naming import NamingOptions
from showrunner.core.track import TrackFlags
from showrunner.stages.metadata import MetadataOptions, MetadataPlan, plan_metadata
from showrunner.stages.metadata.plan import FLAG_FIELDS
from showrunner.stages.mux.options import MuxOptions, Original
from showrunner.stages.tracks import PlannedTrack, PlanRefused, TracksOptions, plan_tracks
from showrunner.tools.mkvtoolnix.propedit import Property

# Marks the new file while it is written and checked; a dot name keeps it out of a scan.
_PARTIAL = ".showrunner-partial.mkv"


class MuxProblemKind(StrEnum):
    # Only ffprobe read the file, so its track IDs mean nothing to mkvmerge.
    IDS_NOT_FROM_MKVMERGE = "ids-not-from-mkvmerge"
    # The file's tracks are not known (a read that was cancelled before it): the new file would hold none of them.
    TRACKS_NOT_READ = "tracks-not-read"


@dataclass(frozen=True, slots=True)
class MuxRefused:
    problems: tuple[MuxProblemKind, ...]


@dataclass(frozen=True, slots=True)
class MuxTrack:
    """A track of the new file with every header value it gets. `planned` says where it comes from: a track of
    the video, or a subtitle file when `planned.external` is set."""

    planned: PlannedTrack
    name: str
    language: Language | None
    flags: TrackFlags


@dataclass(frozen=True, slots=True)
class MuxPlan:
    source: Path  # the video as it is
    output: Path  # the new file's final name
    tracks: tuple[MuxTrack, ...]  # in the order of the new file
    title: str
    duration: float | None  # of the source, for the check after writing
    original: Original
    keep_folder: str
    # The tracks are in another order than the file's (`TrackPlan.reordered`).
    reordered: bool = False
    # Of the source, for the check after writing: mkvmerge copies both into the new file.
    chapters: int = 0
    attachments: int = 0

    @property
    def added(self) -> tuple[SubtitleFile, ...]:
        """The subtitle files that go into the new file, in its order."""
        return tuple(t.planned.external for t in self.tracks if t.planned.external is not None)

    @property
    def partial(self) -> Path:
        """Where the new file is written before it is checked; beside the source, so the final rename is instant."""
        return self.source.with_name(f".{self.output.stem}{_PARTIAL}")

    @property
    def keep_dir(self) -> Path:
        return self.source.parent / self.keep_folder


def output_path(source: Path, suffix: str) -> Path:
    """The new file is always Matroska; with no suffix a Matroska source keeps its name."""
    return source.with_name(f"{source.stem}{suffix}.mkv")


def plan_mux(
    item: MediaItem,
    options: MuxOptions,
    tracks: TracksOptions,
    metadata: MetadataOptions,
    naming: NamingOptions,
    *,
    source: str = "",
) -> MuxPlan | MuxRefused | None:
    """The new file for the item, the reason it cannot be written, or None when the track plan needs no remux.

    With Metadata refusing the file, names, languages and the title stay as they are; the track plan's flags are
    written all the same, since the remux carries out the whole track plan.
    """
    track_plan = plan_tracks(item, tracks)
    if isinstance(track_plan, PlanRefused) or not track_plan.needs_remux:
        return None
    file = item.file
    if not file.tracks:
        return MuxRefused((MuxProblemKind.TRACKS_NOT_READ,))
    if not file.ids_from_mkvmerge:
        return MuxRefused((MuxProblemKind.IDS_NOT_FROM_MKVMERGE,))
    header = plan_metadata(item, metadata, naming, tracks, source=source)
    changes = header.changes if isinstance(header, MetadataPlan) else ()
    title = next((str(c.new) for c in changes if c.prop is Property.TITLE), file.title)

    planned_tracks = []
    for planned in track_plan.kept:
        own = [c for c in changes if c.track_id == planned.track.id]
        name = next((str(c.new) for c in own if c.prop is Property.NAME), planned.track.name)
        tag = next((str(c.new) for c in own if c.prop is Property.LANGUAGE), "")
        language = Language.parse(tag) if tag else planned.track.language
        flags = planned.flags
        for change in own:
            if change.prop in FLAG_FIELDS:
                flags = replace(flags, **{FLAG_FIELDS[change.prop]: bool(change.new)})
        planned_tracks.append(MuxTrack(planned, name, language, flags))
    return MuxPlan(
        file.path,
        output_path(file.path, options.suffix),
        tuple(planned_tracks),
        title,
        file.duration,
        options.original,
        options.keep_folder.strip(),
        track_plan.reordered,
        len(file.chapters),
        len(file.attachments),
    )
