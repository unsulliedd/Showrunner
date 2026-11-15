from __future__ import annotations

from showrunner.core.options.registry import REGISTRY
from showrunner.core.options.serialization import LoadWarning, from_sparse, to_sparse
from showrunner.stages.tracks import (
    FlagShape,
    FlagTest,
    KindTest,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
)


def test_registered_and_the_defaults_change_nothing() -> None:
    assert REGISTRY.get("tracks") is TracksOptions
    assert REGISTRY.defaults()["tracks"] == TracksOptions()
    assert TracksOptions().rules == []
    assert to_sparse(TracksOptions()) == {}


def test_a_rule_list_round_trips() -> None:
    options = TracksOptions(
        rules=[
            TrackRule(
                label="Keep Turkish subtitles",
                match=TrackMatch(kind=KindTest.SUBTITLE, languages=["tr", "und"], forced=FlagTest.UNSET),
                verdict=Verdict.KEEP,
                default=FlagShape.FIRST,
            ),
            TrackRule(
                enabled=False,
                match=TrackMatch(codecs=["DTS"], min_channels=6, max_channels=8, name=r"\bSDH\b", name_is_regex=True),
                verdict=Verdict.DROP,
                forced=FlagShape.FIRST,
            ),
        ],
    )
    warnings: list[LoadWarning] = []
    assert from_sparse(TracksOptions, to_sparse(options), "tracks", warnings) == options
    assert warnings == []
