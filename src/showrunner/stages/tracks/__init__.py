"""Track rules: which tracks of a file stay, which go, and which flags change."""

from showrunner.stages.tracks.check import RuleField, RuleProblem, RuleProblemKind, check_rules
from showrunner.stages.tracks.matching import NO_LANGUAGE, matches
from showrunner.stages.tracks.options import (
    FlagShape,
    FlagTest,
    KindTest,
    PairedFile,
    TrackMatch,
    TrackRule,
    TracksOptions,
    Verdict,
)
from showrunner.stages.tracks.plan import (
    DroppedTrack,
    Flag,
    FlagChange,
    PlannedTrack,
    PlanProblem,
    PlanProblemKind,
    PlanRefused,
    TrackPlan,
    describe_track,
    plan_tracks,
)

__all__ = [
    "NO_LANGUAGE",
    "DroppedTrack",
    "Flag",
    "FlagChange",
    "FlagShape",
    "FlagTest",
    "KindTest",
    "PairedFile",
    "PlanProblem",
    "PlanProblemKind",
    "PlanRefused",
    "PlannedTrack",
    "RuleField",
    "RuleProblem",
    "RuleProblemKind",
    "TrackMatch",
    "TrackPlan",
    "TrackRule",
    "TracksOptions",
    "Verdict",
    "check_rules",
    "describe_track",
    "matches",
    "plan_tracks",
]
