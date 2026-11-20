"""Which stages cannot be planned because their options have a problem, and why. The window and the command line
both ask here, so they agree on what Preview leaves out."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from showrunner.app.jobs.groups import TITLE_TEMPLATE, TRACK_TEMPLATES
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.naming import NamingContext, NamingOptions, Problem, TokenProblem, check_tokens, preview
from showrunner.stages.metadata import MetadataOptions
from showrunner.stages.mux import MuxOptions, NameField, check_names
from showrunner.stages.tracks import RuleProblem, TracksOptions, check_rules

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
    # Only the title template has no title of the file to copy.
    file_title = None if template == TITLE_TEMPLATE else ""
    context = NamingContext(
        _NO_FILE, custom=tuple(naming.custom_tokens), value_maps=naming.value_maps, file_title=file_title
    )
    return preview(getattr(naming, template), context).problems


def blocked_stages(profile: Profile) -> dict[str, StageBlock]:
    """Stage id -> why it is blocked, for every stage whose options have a problem. A problem in a paused rule or
    an empty template blocks nothing, since it decides nothing."""
    found: dict[str, StageBlock] = {}
    tracks: TracksOptions = profile.for_stage("tracks")
    if rule_problems := tuple(p for p in check_rules(tracks) if tracks.rules[p.rule_index].enabled):
        found["tracks"] = StageBlock("tracks", {}, rules=rule_problems)

    metadata: MetadataOptions = profile.for_stage("metadata")
    naming: NamingOptions = profile.for_stage("naming")
    used = [name for name in (TITLE_TEMPLATE, *TRACK_TEMPLATES) if getattr(naming, name)]
    templates = {name: problems for name in used if (problems := template_problems(naming, name))}
    tokens = tuple(check_tokens(naming.custom_tokens, naming.value_maps)) if used else ()
    language = metadata.untagged_language
    bad_language = language if language.strip() and Language.parse(language) is None else ""
    block = StageBlock("metadata", templates, tokens, language=bad_language)
    if block.count:
        found["metadata"] = block

    mux: MuxOptions = profile.for_stage("mux")
    if names := check_names(mux):
        found["mux"] = StageBlock("mux", {}, names=names)
    return found
