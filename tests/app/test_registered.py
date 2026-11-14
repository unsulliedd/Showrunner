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
        .with_options("tracks", replace(TracksOptions(), enabled=True))
        .with_options("metadata", replace(MetadataOptions(), untagged_language="tr"))
    )
    data = profile_to_json(profile)
    assert data["stages"] == {
        "naming": {"title_template": "{show}"},
        "tracks": {"enabled": True},
        "metadata": {"untagged_language": "tr"},
    }
    loaded = profile_from_json("custom", data)
    assert loaded.value == profile
    assert loaded.warnings == []


def test_the_metadata_defaults_follow_the_naming_defaults() -> None:
    assert MetadataOptions().enabled == NamingOptions().enabled


def test_the_command_line_registers_every_stage_at_import() -> None:
    code = (
        "import showrunner.cli.main as m; from showrunner.core.options.registry import REGISTRY; print(*REGISTRY.ids())"
    )
    out = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    assert {"naming", "tracks", "metadata"} <= set(out.stdout.split())
