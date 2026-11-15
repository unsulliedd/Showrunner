"""A profile: a name plus the options of every registered stage, and its JSON form."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from showrunner.app.profiles.errors import UnreadableProfileError
from showrunner.core.options.registry import REGISTRY, OptionsRegistry
from showrunner.core.options.serialization import (
    Loaded,
    LoadWarning,
    WarningKind,
    from_sparse,
    to_sparse,
)

FORMAT_VERSION = 1

# Keys that earlier versions wrote and that no longer mean anything: they are dropped on load without a warning.
# They were on/off switches; what runs now follows from the rules and templates themselves.
_RETIRED = {
    "tracks": {"enabled"},
    "mux": {"enabled"},
    "metadata": {"enabled", "set_title", "set_track_names"},
    "naming": {"enabled"},
}


@dataclass(frozen=True)
class Profile:
    name: str
    # Stage id -> that stage's options instance. Loading fills in every registered stage.
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def defaults(cls, name: str, registry: OptionsRegistry = REGISTRY) -> Profile:
        return cls(name, registry.defaults())

    def for_stage(self, stage_id: str) -> Any:
        return self.options[stage_id]

    def with_options(self, stage_id: str, options: Any) -> Profile:
        return replace(self, options={**self.options, stage_id: options})


def profile_to_json(profile: Profile, registry: OptionsRegistry = REGISTRY) -> dict[str, Any]:
    """Only stages and values that differ from the defaults are written."""
    stages: dict[str, Any] = {}
    for stage_id in registry.ids():
        options = profile.options.get(stage_id)
        if options is None:
            continue
        if not isinstance(options, registry.get(stage_id)):
            raise TypeError(f"options of stage {stage_id!r} have the wrong class: {type(options).__name__}")
        if sparse := to_sparse(options):
            stages[stage_id] = sparse
    return {"format": FORMAT_VERSION, "stages": stages}


def profile_from_json(name: str, data: Any, registry: OptionsRegistry = REGISTRY) -> Loaded[Profile]:
    """Unknown stages and keys are dropped and bad values replaced by defaults, each with a warning."""
    if not isinstance(data, dict):
        raise UnreadableProfileError(name)
    warnings: list[LoadWarning] = []
    version = data.get("format")
    if isinstance(version, int) and not isinstance(version, bool) and version > FORMAT_VERSION:
        warnings.append(LoadWarning(WarningKind.NEWER_FORMAT, "format"))
    stages = data.get("stages", {})
    if not isinstance(stages, dict):
        warnings.append(LoadWarning(WarningKind.WRONG_TYPE, "stages"))
        stages = {}
    options: dict[str, Any] = {}
    for stage_id in registry.ids():
        raw = stages.get(stage_id, {})
        if isinstance(raw, dict) and (retired := _RETIRED.get(stage_id)):
            raw = {key: value for key, value in raw.items() if key not in retired}
        options[stage_id] = from_sparse(registry.get(stage_id), raw, stage_id, warnings)
    warnings.extend(LoadWarning(WarningKind.UNKNOWN_STAGE, key) for key in stages if key not in options)
    return Loaded(Profile(name, options), warnings)
