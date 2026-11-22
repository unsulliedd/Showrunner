"""The kinds of planned change Review shows as groups, each of which a run can leave out.

A group is not a stage: Metadata writes the default and forced flags the track rules choose, and a remux writes the
names Metadata chooses. So a group is left out by planning with its options asking for nothing, as if they were
empty, and every stage then plans what is left.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from showrunner.app.profiles.profile import Profile
from showrunner.stages.subtitles import Approval, Lines, SyncEngine
from showrunner.stages.tracks import FlagShape, TrackRule, Verdict

TITLE_TEMPLATE = "title_template"
TRACK_TEMPLATES = ("video_track_template", "audio_track_template", "subtitle_track_template")


class ChangeGroup(StrEnum):
    # The track choices: tracks dropped, paired subtitle files added, default and forced flags moved, the track
    # order. The new files they ask for go with them.
    TRACKS = "tracks"
    # What Metadata decides on its own: the title, track names, the languages (of untagged tracks, and the ones the
    # track rules give), implied flags.
    NAMES = "names"
    # The finished subtitles: cleaned, synced, re-split or translated, and the new files only they ask for. The paired
    # files they work on are added by the track choices, so leaving those out leaves their subtitle work out too.
    SUBTITLES = "subtitles"


def without(profile: Profile, group: ChangeGroup) -> Profile:
    """`profile` with the options of `group` asking for no change; the rest stays as it is."""
    tracks = profile.for_stage("tracks")
    if group is ChangeGroup.TRACKS:
        # A rule's language is a names change: the rule stays for it, asking nothing else.
        rules = [_language_only(rule) for rule in tracks.rules if rule.language]
        return profile.with_options("tracks", replace(tracks, rules=rules, add_paired=[], order=[]))
    if group is ChangeGroup.SUBTITLES:
        # The reference, the engine settings and the model only say how the work is done, so they stay.
        subtitles = replace(
            profile.for_stage("subtitles"),
            languages={},
            cleanup={},
            sync=SyncEngine.AS_IT_IS,
            lines=Lines.AS_THEY_ARE,
            approval=Approval.NONE,
        )
        return profile.with_options("subtitles", subtitles)
    naming = replace(profile.for_stage("naming"), **dict.fromkeys((TITLE_TEMPLATE, *TRACK_TEMPLATES), ""))
    metadata = replace(profile.for_stage("metadata"), untagged_language="", write_implied_flags=False)
    no_languages = [replace(rule, language="") for rule in tracks.rules]
    return (
        profile.with_options("naming", naming)
        .with_options("metadata", metadata)
        .with_options("tracks", replace(tracks, rules=no_languages))
    )


def _language_only(rule: TrackRule) -> TrackRule:
    return replace(rule, verdict=Verdict.PASS, default=FlagShape.LEAVE, forced=FlagShape.LEAVE)
