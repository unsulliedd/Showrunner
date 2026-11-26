"""The new file one video needs when its track plan drops a track or adds a subtitle file, or when the subtitle stage
makes a finished subtitle for it. Pure logic, nothing is read or written.

The track rules decide which tracks stay, in which order and with which default and forced flags; Metadata
decides the title, names, languages and the flags names imply. A remux writes both, so the header is never edited
separately on a file that is remuxed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.naming import NamingOptions
from showrunner.core.track import Track, TrackFlags, TrackKind
from showrunner.stages.metadata import MetadataOptions, MetadataPlan, plan_metadata
from showrunner.stages.metadata.plan import FLAG_FIELDS
from showrunner.stages.mux.options import MuxOptions, Original
from showrunner.stages.subtitles import FinishedSubtitle, Source
from showrunner.stages.tracks import PlannedTrack, PlanRefused, TracksOptions, plan_tracks
from showrunner.tools.mkvtoolnix.propedit import Property

# A finished subtitle with the path its result is kept at once the subtitle stage made it.
type Finished = tuple[FinishedSubtitle, Path]

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
    the video, or a subtitle file when `planned.external` is set. `content` is the finished subtitle mkvmerge reads in
    their place: a paired file's cleaned or synced result, an embedded track's cleaned text, or a translation, which
    has neither and stands in with a track of its own."""

    planned: PlannedTrack
    name: str
    language: Language | None
    flags: TrackFlags
    content: Path | None = None


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
        """The subtitle files beside the video that go into the new file, in its order, as they are or as the finished
        subtitle made of them; they are moved away with the original."""
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
    finished: Sequence[Finished] = (),
) -> MuxPlan | MuxRefused | None:
    """The new file for the item, the reason it cannot be written, or None when neither the track plan nor a finished
    subtitle needs one. `finished` are the subtitle stage's results for the file: each takes the place of the paired
    file or embedded track it was made of, and a translation goes after the file's tracks.

    With Metadata refusing the file, names, languages and the title stay as they are; the track plan's flags are
    written all the same, since the remux carries out the whole track plan.
    """
    track_plan = plan_tracks(item, tracks)
    if isinstance(track_plan, PlanRefused) or not (track_plan.needs_remux or finished):
        return None
    file = item.file
    if not file.tracks:
        return MuxRefused((MuxProblemKind.TRACKS_NOT_READ,))
    if not file.ids_from_mkvmerge:
        return MuxRefused((MuxProblemKind.IDS_NOT_FROM_MKVMERGE,))
    header = plan_metadata(item, metadata, naming, tracks, source=source, remux=True)
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
        planned_tracks.append(MuxTrack(planned, name, language, flags, _content(planned, finished)))
    # Below every paired file's stand-in, so no two tracks of the plan share an id.
    lowest = -len(item.subtitles)
    translations = [(f, path) for f, path in finished if f.source is Source.TRANSLATION]
    for n, (translation, path) in enumerate(translations, 1):
        track = Track(lowest - n, TrackKind.SUBTITLE, language=translation.language)
        planned_tracks.append(MuxTrack(PlannedTrack(track), translation.name, translation.language, track.flags, path))
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


def _content(planned: PlannedTrack, finished: Sequence[Finished]) -> Path | None:
    """The result that takes the track's place in the new file: the one made of its paired file or of the track."""
    for subtitle, path in finished:
        if subtitle.source is Source.PAIRED and planned.external is not None and subtitle.paired == planned.external:
            return path
        if subtitle.source is Source.EMBEDDED and planned.external is None and subtitle.track == planned.track:
            return path
    return None
