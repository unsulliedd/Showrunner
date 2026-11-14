"""Options of the naming engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from showrunner.core.naming.custom import CustomToken
from showrunner.core.options.registry import REGISTRY


@REGISTRY.register("naming")
@dataclass(frozen=True, slots=True)
class NamingOptions:
    # Off: stages that set names (title, track names, file names) leave them as they are.
    enabled: bool = True
    # The MKV title and the track names. By default the title is the file's name, and each track name adds
    # what is read from the track: resolution, HDR and source for video, codec and channels for audio. Audio and
    # subtitle names end in their flags, so a commentary or forced track keeps saying so after renaming.
    title_template: str = "{file_name}"
    video_track_template: str = "{file_name} ({resolution}[ {hdr}] {source})"
    audio_track_template: str = "{file_name} ({codec} {channels}[ {flags}])"
    subtitle_track_template: str = "{file_name}[ ({flags})]"
    # The user's own tokens, usable in every template; they may not reuse a built-in token's name.
    custom_tokens: list[CustomToken] = field(default_factory=list)
    # Token name -> value read -> text to use instead. Applies to built-in and defined tokens; the default
    # display names (codecs, HDR kinds) are rewritten the same way.
    value_maps: dict[str, dict[str, str]] = field(default_factory=dict)
