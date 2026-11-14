from __future__ import annotations

from dataclasses import replace

from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.naming import CustomKind, CustomToken, ProblemKind
from showrunner.stages.tracks import TrackMatch, TrackRule, TracksOptions


def profile(**stages: object) -> Profile:
    base = Profile.defaults("Test")
    for stage_id, changes in stages.items():
        base = base.with_options(stage_id, replace(base.for_stage(stage_id), **changes))  # type: ignore[arg-type]
    return base


def test_the_defaults_block_nothing() -> None:
    assert blocked_stages(profile()) == {}


def test_an_unknown_token_blocks_metadata() -> None:
    blocks = blocked_stages(profile(naming={"audio_track_template": "{language} {chanels}"}))
    assert list(blocks) == ["metadata"]
    (problem,) = blocks["metadata"].templates["audio_track_template"]
    assert (problem.kind, problem.start, problem.end) == (ProblemKind.UNKNOWN_TOKEN, 11, 20)
    assert blocks["metadata"].count == 1


def test_an_unused_template_blocks_nothing() -> None:
    broken = {"audio_track_template": "{nope}"}
    assert blocked_stages(profile(naming=broken, metadata={"set_track_names": False})) == {}
    assert blocked_stages(profile(naming={**broken, "enabled": False})) == {}
    assert blocked_stages(profile(naming=broken, metadata={"enabled": False})) == {}


def test_a_broken_token_definition_blocks_metadata() -> None:
    custom = [CustomToken("group", CustomKind.PATTERN, "(")]
    assert len(blocked_stages(profile(naming={"custom_tokens": custom}))["metadata"].tokens) == 1


def test_an_untagged_language_that_is_not_one_blocks_metadata() -> None:
    assert blocked_stages(profile(metadata={"untagged_language": "xx1"}))["metadata"].language == "xx1"


def test_a_broken_rule_blocks_tracks_only_while_it_is_on() -> None:
    rule = TrackRule(match=TrackMatch(languages=["egn"]))
    blocks = blocked_stages(profile(tracks={"enabled": True, "rules": [rule]}))
    assert list(blocks) == ["tracks"]
    assert blocks["tracks"].rules[0].detail == "egn"
    off = TracksOptions(enabled=True, rules=[replace(rule, enabled=False)])
    assert blocked_stages(profile(tracks={"enabled": off.enabled, "rules": off.rules})) == {}
    assert blocked_stages(profile(tracks={"enabled": False, "rules": [rule]})) == {}
