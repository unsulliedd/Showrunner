from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

from showrunner.app.profiles import registered
from showrunner.app.profiles.profile import Profile, profile_from_json, profile_to_json
from showrunner.core.naming import NamingOptions
from showrunner.core.options.registry import REGISTRY
from showrunner.stages.metadata import MetadataOptions
from showrunner.stages.tracks import TracksOptions


def test_every_stage_is_registered_once_the_module_is_imported() -> None:
    assert set(REGISTRY.ids()) >= {"scan", "naming", "tracks", "metadata"}
    assert len(registered.OPTIONS_MODULES) == len(REGISTRY.ids())


def test_a_saved_profile_keeps_the_naming_tracks_and_metadata_sections() -> None:
    profile = (
        Profile.defaults("custom")
        .with_options("naming", replace(NamingOptions(), title_template="{show}"))
        .with_options("tracks", replace(TracksOptions(), flags_from_names=False))
        .with_options("metadata", replace(MetadataOptions(), untagged_language="tr"))
    )
    data = profile_to_json(profile)
    assert data["stages"] == {
        "naming": {"title_template": "{show}"},
        "tracks": {"flags_from_names": False},
        "metadata": {"untagged_language": "tr"},
    }
    loaded = profile_from_json("custom", data)
    assert loaded.value == profile
    assert loaded.warnings == []


def test_keys_of_retired_switches_are_dropped_without_a_warning() -> None:
    data = {
        "format": 1,
        "stages": {
            "scan": {"enabled": False},
            "tracks": {"enabled": True, "flags_from_names": False},
            "mux": {"enabled": True, "suffix": " [new]"},
            "metadata": {"enabled": False, "set_title": False, "set_track_names": False, "untagged_language": "tr"},
            "naming": {"enabled": False, "title_template": "{show}"},
        },
    }
    loaded = profile_from_json("old", data)
    assert loaded.warnings == []
    assert loaded.value.for_stage("tracks") == TracksOptions(flags_from_names=False)
    assert loaded.value.for_stage("scan") == REGISTRY.get("scan")()
    assert loaded.value.for_stage("mux").suffix == " [new]"
    assert loaded.value.for_stage("metadata") == MetadataOptions(untagged_language="tr")
    assert loaded.value.for_stage("naming") == replace(NamingOptions(), title_template="{show}")
    assert "enabled" not in profile_to_json(loaded.value)["stages"]["tracks"]


def test_a_retired_key_is_still_unknown_on_a_stage_that_never_had_it() -> None:
    loaded = profile_from_json("old", {"format": 1, "stages": {"tracks": {"set_title": True}}})
    assert [w.location for w in loaded.warnings] == ["tracks.set_title"]


def test_the_command_line_registers_every_stage_at_import() -> None:
    code = (
        "import showrunner.cli.main as m; from showrunner.core.options.registry import REGISTRY; print(*REGISTRY.ids())"
    )
    out = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    assert {"naming", "tracks", "metadata"} <= set(out.stdout.split())
