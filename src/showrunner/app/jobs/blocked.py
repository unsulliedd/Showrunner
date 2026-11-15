"""Which stages cannot be planned because their options have a problem, and why. The window and the command line
both ask here, so they agree on what Preview leaves out."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.naming import NamingContext, NamingOptions, Problem, TokenProblem, check_tokens, preview
from showrunner.stages.metadata import MetadataOptions
from showrunner.stages.mux import MuxOptions, NameField, check_names
from showrunner.stages.tracks import RuleProblem, TracksOptions, check_rules

TITLE_TEMPLATE = "title_template"
TRACK_TEMPLATES = ("video_track_template", "audio_track_template", "subtitle_track_template")

# Unknown tokens, bad padding and cycles show only when a template is rendered; an empty file is enough for that.
_NO_FILE = MediaItem(Movie(""), MediaFile(Path("file.mkv"), ""))


@dataclass(frozen=True, slots=True)
class StageBlock:
    """Why one stage is not planned. Only the fields of that stage's own checks are filled."""

    stage: str
    # Template option name -> its problems, for the templates the stage uses.
    templates: dict[str, tuple[Problem, ...]]
    tokens: tuple[TokenProblem, ...] = ()
    rules: tuple[RuleProblem, ...] = ()
    language: str = ""  # an untagged-track language that is not one
    names: tuple[NameField, ...] = ()  # Mux fields that cannot be part of a file name

    @property
    def count(self) -> int:
        problems = sum(len(p) for p in self.templates.values()) + len(self.tokens) + len(self.rules)
        return problems + bool(self.language) + len(self.names)


def template_problems(naming: NamingOptions, template: str) -> tuple[Problem, ...]:
    """The problems of one template, without a file."""
    context = NamingContext(_NO_FILE, custom=tuple(naming.custom_tokens), value_maps=naming.value_maps)
    return preview(getattr(naming, template), context).problems


def blocked_stages(profile: Profile) -> dict[str, StageBlock]:
    """Stage id -> why it is blocked, for every switched-on stage whose options have a problem. A problem in a
    switched-off rule or an unused template blocks nothing, since it decides nothing."""
    found: dict[str, StageBlock] = {}
    tracks: TracksOptions = profile.for_stage("tracks")
    if tracks.enabled:
        rule_problems = tuple(p for p in check_rules(tracks) if tracks.rules[p.rule_index].enabled)
        if rule_problems:
            found["tracks"] = StageBlock("tracks", {}, rules=rule_problems)

    metadata: MetadataOptions = profile.for_stage("metadata")
    naming: NamingOptions = profile.for_stage("naming")
    if metadata.enabled:
        used = []
        if naming.enabled and metadata.set_title:
            used.append(TITLE_TEMPLATE)
        if naming.enabled and metadata.set_track_names:
            used.extend(TRACK_TEMPLATES)
        templates = {name: problems for name in used if (problems := template_problems(naming, name))}
        tokens = tuple(check_tokens(naming.custom_tokens, naming.value_maps)) if used else ()
        language = metadata.untagged_language
        bad_language = language if language.strip() and Language.parse(language) is None else ""
        block = StageBlock("metadata", templates, tokens, language=bad_language)
        if block.count:
            found["metadata"] = block

    mux: MuxOptions = profile.for_stage("mux")
    if mux.enabled and (names := check_names(mux)):
        found["mux"] = StageBlock("mux", {}, names=names)
    return found
