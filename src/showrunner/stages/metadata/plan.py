"""The header changes one file needs. Pure logic, nothing is read or written."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.core.naming import NamingContext, NamingOptions, Problem, preview
from showrunner.core.track import Track, TrackKind, flags_with_name
from showrunner.stages.metadata.options import MetadataOptions
from showrunner.stages.tracks import (
    FlagShape,
    PlannedTrack,
    PlanRefused,
    TrackPlan,
    TrackRule,
    TracksOptions,
    language_given,
    plan_tracks,
)
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


def named_tracks(item: MediaItem, tracks: TracksOptions) -> tuple[TrackPlan, TracksOptions]:
    """The tracks the file keeps, which the names are made for, and the track options that kept them."""
    track_plan = plan_tracks(item, tracks)
    if isinstance(track_plan, PlanRefused):
        # The file keeps its tracks as they are, so names and languages are planned for those tracks and the
        # rules' flag changes are left out with the rest of the refused plan.
        tracks = replace(tracks, rules=[], add_paired=[])
        track_plan = plan_tracks(item, tracks)
        assert isinstance(track_plan, TrackPlan)
    return track_plan, tracks


def naming_context(
    item: MediaItem,
    naming: NamingOptions,
    tracks: TracksOptions,
    track: PlannedTrack | None,
    source: str = "",
    language: str = "",
) -> NamingContext:
    """What a template reads for the file's title (`track` None) or for one kept track. `language` is the tag the
    track gets when it changes (`language_after`)."""
    # The flags and the language after the rules, so `{flags}` and `{language}` name what the track will be.
    named = replace(track.track, flags=track.flags) if track else None
    if named and language and (after := Language.parse(language)) is not None:
        named = replace(named, language=after)
    template = _TEMPLATES[named.kind] if named else "title_template"
    return NamingContext(
        item,
        named,
        source,
        naming.custom_tokens,
        naming.value_maps,
        flags_from_names=tracks.flags_from_names,
        space=naming.space_for(template),
        episode_code_format=naming.episode_code_format,
    )


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
    refusals: list[MetadataProblem] = []
    if not file.ids_from_mkvmerge:
        refusals.append(MetadataProblem(MetadataProblemKind.IDS_NOT_FROM_MKVMERGE))
    # mkvpropedit edits Matroska and WebM files only.
    if file.container.casefold() not in {"matroska", "webm"}:
        refusals.append(MetadataProblem(MetadataProblemKind.NOT_MATROSKA, detail=file.container))
    # The rules that give a language are read from the options as they were made: a file whose tracks the rules
    # refuse to change still gets the languages they give.
    language_rules, from_names = tracks.rules, tracks.flags_from_names
    track_plan, tracks = named_tracks(item, tracks)
    invalid: list[MetadataProblem] = []  # a problem of the options, which refuses every file
    language = _language(options.untagged_language, invalid)
    given: dict[str, str] = {}  # the tag a rule gives, as the rule writes it, to the tag it comes to

    found: dict[str, dict[Problem, None]] = {}  # template option -> its problems, without repeats

    def render(template: str, track: PlannedTrack | None, tag: str = "") -> str:
        result = preview(getattr(naming, template), naming_context(item, naming, tracks, track, source, tag))
        found.setdefault(template, {}).update(dict.fromkeys(result.problems))
        return result.text

    # A flag a rule picks tracks for ("the first Turkish subtitle is forced") is left to the rules, so that a
    # name cannot add a second track to the one they chose.
    ruled = {"forced"} if any(r.enabled and r.forced is FlagShape.FIRST for r in tracks.rules) else set()

    changes: list[HeaderChange] = []
    # An empty result leaves a title or name alone: a template never clears one by accident.
    if (title := render("title_template", None)) and title != file.title:
        changes.append(HeaderChange(Property.TITLE, file.title, title))
    # A subtitle file that is added is planned under its stand-in track's negative ID; only a remux adds files, so
    # those changes go into the remux and never to mkvpropedit.
    for planned in track_plan.kept:
        track = planned.track
        is_video = track.kind is TrackKind.VIDEO
        wanted = "" if is_video else _wanted_language(track, language, language_rules, from_names, given, invalid)
        name = render(_TEMPLATES[track.kind], planned, wanted)
        if name and name != track.name:
            changes.append(HeaderChange(Property.NAME, track.name, name, track.id))
        if wanted:
            was = track.language.ietf if track.language else ""
            changes.append(HeaderChange(Property.LANGUAGE, was, wanted, track.id))
        changes += _flag_changes(planned, track_plan.needs_remux, options.write_implied_flags, ruled)

    problems = [
        MetadataProblem(MetadataProblemKind.TEMPLATE, template, tuple(template_problems))
        for template, template_problems in found.items()
        if template_problems
    ]
    # A file the options ask nothing of is not refused for what it is: nothing would be edited on it.
    if invalid or (refusals and (changes or problems)):
        return MetadataRefused(tuple(refusals + invalid))
    if problems:
        return MetadataRefused(tuple(problems))
    return MetadataPlan(file.path, tuple(changes), track_plan.needs_remux)


def language_after(track: Track, rules: list[TrackRule], from_names: bool, untagged: str = "") -> str:
    """The tag the plan gives `track` (a rule's, else the one for untagged tracks), empty when it keeps its language."""
    if track.kind is TrackKind.VIDEO:
        return ""
    return _wanted_language(track, _language(untagged, []), rules, from_names, {}, [])


def _wanted_language(
    track: Track,
    untagged: str,
    rules: list[TrackRule],
    from_names: bool,
    given: dict[str, str],
    refusals: list[MetadataProblem],
) -> str:
    """The tag the track gets, empty when it keeps its language: the one a rule gives it, else the one for untagged
    tracks when it has none."""
    if tag := language_given(rules, track, from_names):
        if tag not in given:
            given[tag] = _language(tag, refusals)
        wanted = given[tag]
    else:
        wanted = untagged if track.language is None else ""
    return "" if track.language is not None and wanted == track.language.ietf else wanted


def _language(tag: str, refusals: list[MetadataProblem]) -> str:
    if not tag:
        return ""
    if (language := Language.parse(tag)) is None:
        if not any(r.detail == tag for r in refusals):
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
