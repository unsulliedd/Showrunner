from __future__ import annotations

from showrunner.core.naming import CustomKind, CustomToken, NamingOptions, PatternSource
from showrunner.core.options.registry import REGISTRY
from showrunner.core.options.serialization import LoadWarning, from_sparse, to_sparse


def test_registered_with_the_defaults() -> None:
    assert REGISTRY.get("naming") is NamingOptions
    assert REGISTRY.defaults()["naming"] == NamingOptions()


def test_defaults_write_nothing_and_changes_round_trip() -> None:
    assert to_sparse(NamingOptions()) == {}
    options = NamingOptions(
        audio_track_template="{codec}",
        custom_tokens=[
            CustomToken("group", CustomKind.CONSTANT, "GRP"),
            CustomToken("tag", CustomKind.PATTERN, r"-([^-]+)$", PatternSource.FOLDER_1),
        ],
        value_maps={"codec": {"DTS": "DTS-HD Master Audio"}},
    )
    warnings: list[LoadWarning] = []
    assert from_sparse(NamingOptions, to_sparse(options), "naming", warnings) == options
    assert warnings == []
