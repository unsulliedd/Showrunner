"""The header changes one file needs. Pure logic, nothing is read or written."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.core.naming import NamingContext, NamingOptions, Problem, preview
from showrunner.core.track import TrackKind, flags_with_name
from showrunner.stages.metadata.options import MetadataOptions
from showrunner.stages.tracks import FlagShape, PlannedTrack, PlanRefused, TrackPlan, TracksOptions, plan_tracks
from showrunner.tools.mkvtoolnix.propedit import Edit, Property

# The flag properties and the `TrackFlags` field each one reads.
FLAG_FIELDS: dict[Property, str] = {
    Property.FLAG_DEFAULT: "default",
    Property.FLAG_FORCED: "forced",
    Property.FLAG_HEARING_IMPAIRED: "hearing_impaired",
    Property.FLAG_COMMENTARY: "commentary",
}
_BY_FIELD = {field: prop for prop, field in FLAG_FIELDS.items()}
# The flags a name can imply, see `flags_with_name`.
_IMPLIED = (Property.FLAG_COMMENTARY, Property.FLAG_HEARING_IMPAIRED, Property.FLAG_FORCED)
_TEMPLATES = {
    TrackKind.VIDEO: "video_track_template",
    TrackKind.AUDIO: "audio_track_template",
    TrackKind.SUBTITLE: "subtitle_track_template",
}


class MetadataProblemKind(StrEnum):
    # Only ffprobe read the file, so its track IDs mean nothing to mkvpropedit.
    IDS_NOT_FROM_MKVMERGE = "ids-not-from-mkvmerge"
    NOT_MATROSKA = "not-matroska"  # detail: the container
    TEMPLATE = "template"  # `template` is the option's name, `template_problems` what is wrong in it
    INVALID_LANGUAGE = "invalid-language"  # detail: the tag
    # No longer produced: a file the track rules refuse is planned with its tracks as they are.
    TRACKS_REFUSED = "tracks-refused"  # `refused` holds the reasons of the track plan


@dataclass(frozen=True, slots=True)
class MetadataProblem:
    kind: MetadataProblemKind
    template: str = ""
    template_problems: tuple[Problem, ...] = ()
    detail: str = ""
    refused: PlanRefused | None = None


@dataclass(frozen=True, slots=True)
class MetadataRefused:
    """Returned instead of a plan when the file cannot be planned; nothing would be edited."""

    problems: tuple[MetadataProblem, ...]


@dataclass(frozen=True, slots=True)
class HeaderChange:
    """One property with the value the file has and the value it gets.

    Values are text for the title, names and languages (a language is its IETF tag, empty for none) and
    a boolean for flags.
    """

    prop: Property
    old: str | bool
    new: str | bool
    track_id: int | None = None  # mkvmerge track ID; None for the title

    @property
    def edit(self) -> Edit:
        return Edit(self.prop, self.new, self.track_id)


@dataclass(frozen=True, slots=True)
class MetadataPlan:
    path: Path
    changes: tuple[HeaderChange, ...]
    # True when the track rules drop a track or add a subtitle file. The remux then writes `changes` and
    # the final flags of the track plan, so the header is not edited in place and `changes` holds no
    # default or forced flag from the track plan.
    needs_remux: bool = False


def plan_metadata(
    item: MediaItem,
    options: MetadataOptions,
    naming: NamingOptions,
    tracks: TracksOptions,
    *,
    source: str = "",
) -> MetadataPlan | MetadataRefused:
    """The header changes for the file, or the problems that stop the plan."""
    file = item.file
    if not options.enabled:
        return MetadataPlan(file.path, ())
    refusals: list[MetadataProblem] = []
    if not file.ids_from_mkvmerge:
        refusals.append(MetadataProblem(MetadataProblemKind.IDS_NOT_FROM_MKVMERGE))
    # mkvpropedit edits Matroska and WebM files only.
    if file.container.casefold() not in {"matroska", "webm"}:
        refusals.append(MetadataProblem(MetadataProblemKind.NOT_MATROSKA, detail=file.container))
    track_plan = plan_tracks(item, tracks)
    if isinstance(track_plan, PlanRefused):
        # The file keeps its tracks as they are, so names and languages are planned for those tracks and the
        # rules' flag changes are left out with the rest of the refused plan.
        tracks = replace(tracks, enabled=False)
        track_plan = plan_tracks(item, tracks)
        assert isinstance(track_plan, TrackPlan)
    language = _language(options.untagged_language, refusals)
    if refusals:
        return MetadataRefused(tuple(refusals))

    found: dict[str, dict[Problem, None]] = {}  # template option -> its problems, without repeats

    def render(template: str, track: PlannedTrack | None) -> str:
        # The flags after the rules, so `{flags}` names what the track will be.
        named = replace(track.track, flags=track.flags) if track else None
        context = NamingContext(
            item, named, source, naming.custom_tokens, naming.value_maps, flags_from_names=tracks.flags_from_names
        )
        result = preview(getattr(naming, template), context)
        found.setdefault(template, {}).update(dict.fromkeys(result.problems))
        return result.text

    # A flag a rule picks tracks for ("the first Turkish subtitle is forced") is left to the rules, so that a
    # name cannot add a second track to the one they chose.
    ruled = (
        {"forced"} if tracks.enabled and any(r.enabled and r.forced is FlagShape.FIRST for r in tracks.rules) else set()
    )

    changes: list[HeaderChange] = []
    # An empty result leaves a title or name alone: a template never clears one by accident.
    if naming.enabled and options.set_title and (title := render("title_template", None)) and title != file.title:
        changes.append(HeaderChange(Property.TITLE, file.title, title))
    # A subtitle file that is added is planned under its stand-in track's negative ID; only a remux adds files, so
    # those changes go into the remux and never to mkvpropedit.
    for planned in track_plan.kept:
        track = planned.track
        if naming.enabled and options.set_track_names:
            name = render(_TEMPLATES[track.kind], planned)
            if name and name != track.name:
                changes.append(HeaderChange(Property.NAME, track.name, name, track.id))
        if language and track.language is None and track.kind is not TrackKind.VIDEO:
            changes.append(HeaderChange(Property.LANGUAGE, "", language, track.id))
        changes += _flag_changes(planned, track_plan.needs_remux, options.write_implied_flags, ruled)

    if problems := [
        MetadataProblem(MetadataProblemKind.TEMPLATE, template, tuple(template_problems))
        for template, template_problems in found.items()
        if template_problems
    ]:
        return MetadataRefused(tuple(problems))
    return MetadataPlan(file.path, tuple(changes), track_plan.needs_remux)


def _language(tag: str, refusals: list[MetadataProblem]) -> str:
    if not tag:
        return ""
    if (language := Language.parse(tag)) is None:
        refusals.append(MetadataProblem(MetadataProblemKind.INVALID_LANGUAGE, detail=tag))
        return ""
    return language.ietf


def _flag_changes(planned: PlannedTrack, needs_remux: bool, write_implied: bool, ruled: set[str]) -> list[HeaderChange]:
    track = planned.track
    changes = []
    if not needs_remux:
        changes += [
            HeaderChange(_BY_FIELD[change.flag.value], getattr(track.flags, change.flag.value), change.value, track.id)
            for change in planned.flag_changes
        ]
    if write_implied:
        # Read from the name the file has now, since a template may replace it.
        implied, after_rules = flags_with_name(track), planned.flags
        for prop in _IMPLIED:
            field = FLAG_FIELDS[prop]
            if field not in ruled and getattr(implied, field) and not getattr(after_rules, field):
                changes.append(HeaderChange(prop, False, True, track.id))
    return changes
