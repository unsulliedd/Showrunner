"""Metadata: the title, track names, languages and flags a file's header should have."""

from showrunner.stages.metadata.apply import ApplyResult, apply_metadata
from showrunner.stages.metadata.options import MetadataOptions
from showrunner.stages.metadata.plan import (
    HeaderChange,
    MetadataPlan,
    MetadataProblem,
    MetadataProblemKind,
    MetadataRefused,
    language_after,
    named_tracks,
    naming_context,
    plan_metadata,
)

__all__ = [
    "ApplyResult",
    "HeaderChange",
    "MetadataOptions",
    "MetadataPlan",
    "MetadataProblem",
    "MetadataProblemKind",
    "MetadataRefused",
    "apply_metadata",
    "language_after",
    "named_tracks",
    "naming_context",
    "plan_metadata",
]
