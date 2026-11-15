"""Options of the metadata stage: which header values of a Matroska file the app sets."""

from __future__ import annotations

from dataclasses import dataclass

from showrunner.core.options.registry import REGISTRY


@REGISTRY.register("metadata")
@dataclass(frozen=True, slots=True)
class MetadataOptions:
    # The title and track names come from the naming options' templates; an empty one leaves them as they are.
    # A language tag (`tr`, `pt-BR`) given to every audio and subtitle track that has no language; empty
    # leaves such tracks alone. Languages are not changed on tracks that already have one.
    untagged_language: str = ""
    # Write the commentary, hearing impaired and forced flags that a track's current name implies into the
    # header, so the file is right without the name. Off by default, so that nothing is written the user did not
    # ask for.
    write_implied_flags: bool = False
