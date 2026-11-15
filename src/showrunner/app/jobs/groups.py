"""The kinds of planned change Review shows as groups, each of which a run can leave out.

A group is not a stage: Metadata writes the default and forced flags the track rules choose, and a remux writes the
names Metadata chooses. So a group is left out by planning with its options asking for nothing, as if they were
empty, and every stage then plans what is left.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from showrunner.app.profiles.profile import Profile

TITLE_TEMPLATE = "title_template"
TRACK_TEMPLATES = ("video_track_template", "audio_track_template", "subtitle_track_template")


class ChangeGroup(StrEnum):
    # The track rules: tracks dropped, paired subtitle files added, default and forced flags moved. Every new file
    # goes with them, since only the rules ask for one.
    TRACKS = "tracks"
    # What Metadata decides on its own: the title, track names, the language of untagged tracks, implied flags.
    NAMES = "names"


def without(profile: Profile, group: ChangeGroup) -> Profile:
    """`profile` with the options of `group` asking for no change; the rest stays as it is."""
    if group is ChangeGroup.TRACKS:
        return profile.with_options("tracks", replace(profile.for_stage("tracks"), rules=[]))
    naming = replace(profile.for_stage("naming"), **dict.fromkeys((TITLE_TEMPLATE, *TRACK_TEMPLATES), ""))
    metadata = replace(profile.for_stage("metadata"), untagged_language="", write_implied_flags=False)
    return profile.with_options("naming", naming).with_options("metadata", metadata)
