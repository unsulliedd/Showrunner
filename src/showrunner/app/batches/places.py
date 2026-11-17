"""A place's own choices and how they lie over the ones it receives.

A season, an episode or a movie holds only the fields it set itself, by stage: `{"tracks": {"order": [...]}}`. Every
field set there wins over the parent's, the track rules aside: the place's own rules go first and the parent's follow
(`layered_rules`), so a choice made on a show still decides every track the season leaves to it. A field holds a value
or is absent; equal to the default is still set, so a season can give back a show's `False` its `True`. Removing a
field, or the whole layer, makes the place follow its parent again.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

from showrunner.app.batches.choices import layered_rules
from showrunner.app.profiles.profile import Profile
from showrunner.core.options.registry import REGISTRY, OptionsRegistry
from showrunner.core.options.serialization import LoadWarning, from_fields, to_fields

# Stage id -> field name -> the value the place set.
type Layer = dict[str, dict[str, Any]]

RULES = ("tracks", "rules")


def combine(profile: Profile, layer: Layer) -> Profile:
    """`profile`, the options a place receives, with the place's own fields laid over it."""
    for stage_id, values in layer.items():
        options = profile.for_stage(stage_id)
        changes = dict(values)
        if (stage_id, "rules") == RULES and "rules" in changes:
            changes["rules"] = layered_rules(changes["rules"], options.rules)
        profile = profile.with_options(stage_id, replace(options, **changes))
    return profile


def with_options(layer: Layer, stage_id: str, options: Any, received: Any) -> Layer:
    """`layer` after the place's options of one stage became `options`; `received` are that stage's options from
    above. A field equal to what is received is not kept, so the place follows its parent there; the rules are the
    place's own rules, kept while there are any."""
    own: dict[str, Any] = {}
    for field in fields(options):
        value = getattr(options, field.name)
        if (stage_id, field.name) == RULES:
            if value:
                own[field.name] = list(value)
        elif value != getattr(received, field.name):
            own[field.name] = value
    rest = {key: values for key, values in layer.items() if key != stage_id}
    return {**rest, stage_id: own} if own else rest


def own_rules(layer: Layer) -> list[Any]:
    return list(layer.get("tracks", {}).get("rules", []))


def difference(edited: Profile, base: Profile, received: Profile) -> Layer:
    """The own choices of a place stored whole before places passed choices down: `edited`, what it planned with,
    against `base`, what it started from. A field left as `base` has it, or equal to what the place now receives, is
    not its own. Rules that end with the base's keep only what comes before them; any other changed list is kept
    whole, so every track the place decided is decided as before and only what it left open follows the parent."""
    layer: Layer = {}
    for stage_id, options in edited.options.items():
        start, parent = base.for_stage(stage_id), received.for_stage(stage_id)
        own: dict[str, Any] = {}
        for field in fields(options):
            value, first = getattr(options, field.name), getattr(start, field.name)
            if value in (first, getattr(parent, field.name)):
                continue
            if (stage_id, field.name) == RULES and first and value[-len(first) :] == first:
                value = value[: -len(first)]
            if (stage_id, field.name) != RULES or value:
                own[field.name] = value
        if own:
            layer[stage_id] = own
    return layer


def layer_to_json(layer: Layer) -> dict[str, Any]:
    return {stage_id: to_fields(REGISTRY.get(stage_id)(**values), values) for stage_id, values in layer.items()}


def layer_from_json(data: Any, registry: OptionsRegistry = REGISTRY) -> Layer:
    """Forgiving like a profile file: an unknown stage or field, or a value of the wrong type, is skipped."""
    warnings: list[LoadWarning] = []
    layer: Layer = {}
    for stage_id, raw in data.items() if isinstance(data, dict) else ():
        if stage_id in registry.ids() and (values := from_fields(registry.get(stage_id), raw, stage_id, warnings)):
            layer[stage_id] = values
    return layer
