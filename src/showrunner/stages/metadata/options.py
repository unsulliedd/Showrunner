"""Options of the metadata stage: which header values of a Matroska file the app sets."""

from __future__ import annotations

from dataclasses import dataclass

from showrunner.core.options.registry import REGISTRY


@REGISTRY.register("metadata")
@dataclass(frozen=True, slots=True)
class MetadataOptions:
    # Off: no header is edited, including the default and forced flags the track rules change.
    enabled: bool = True
    # The templates are the naming options', whose own switch turns every name off at once.
    set_title: bool = True
    set_track_names: bool = True
    # A language tag (`tr`, `pt-BR`) given to every audio and subtitle track that has no language; empty
    # leaves such tracks alone. Languages are not changed on tracks that already have one.
    untagged_language: str = ""
    # Write the commentary, hearing impaired and forced flags that a track's current name implies into the
    # header, so the file is right without the name.
    write_implied_flags: bool = True
