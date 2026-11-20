from __future__ import annotations

from dataclasses import replace

from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.naming import CustomKind, CustomToken, ProblemKind
from showrunner.stages.tracks import TrackMatch, TrackRule


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


def test_an_empty_template_blocks_nothing_and_needs_no_token_check() -> None:
    empty = dict.fromkeys(
        ("title_template", "video_track_template", "audio_track_template", "subtitle_track_template"), ""
    )
    broken_token = [CustomToken("group", CustomKind.PATTERN, "(")]
    assert blocked_stages(profile(naming={**empty, "custom_tokens": broken_token})) == {}


def test_a_broken_token_definition_blocks_metadata() -> None:
    custom = [CustomToken("group", CustomKind.PATTERN, "(")]
    naming = {"custom_tokens": custom, "title_template": "{file_name}"}
    assert len(blocked_stages(profile(naming=naming))["metadata"].tokens) == 1


def test_an_untagged_language_that_is_not_one_blocks_metadata() -> None:
    assert blocked_stages(profile(metadata={"untagged_language": "xx1"}))["metadata"].language == "xx1"


def test_a_broken_rule_blocks_tracks_only_while_it_is_on() -> None:
    rule = TrackRule(match=TrackMatch(languages=["egn"]))
    blocks = blocked_stages(profile(tracks={"rules": [rule]}))
    assert list(blocks) == ["tracks"]
    assert blocks["tracks"].rules[0].detail == "egn"
    assert blocked_stages(profile(tracks={"rules": [replace(rule, enabled=False)]})) == {}


def test_file_title_blocks_the_title_template_only() -> None:
    blocks = blocked_stages(profile(naming={"title_template": "{file_title}", "audio_track_template": "{file_title}"}))
    assert list(blocks["metadata"].templates) == ["title_template"]
    (problem,) = blocks["metadata"].templates["title_template"]
    assert (problem.kind, problem.detail) == (ProblemKind.NOT_HERE, "file_title")
    assert blocked_stages(profile(naming={"title_template": "", "audio_track_template": "{file_title} {codec}"})) == {}
