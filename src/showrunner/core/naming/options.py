"""Options of the naming engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from showrunner.core.naming.custom import CustomToken
from showrunner.core.options.registry import REGISTRY

# Templates offered for an empty template field: the title is the file's name, and each track name adds what is
# read from the track (resolution, HDR and source for video; codec and channels for audio). Audio and subtitle names
# end in their flags, so a commentary or forced track keeps saying so after renaming.
SUGGESTED_TEMPLATES = MappingProxyType(
    {
        "title_template": "{file_name}",
        "video_track_template": "{file_name} ({resolution}[ {hdr}] {source})",
        "audio_track_template": "{file_name} ({codec} {channels}[ {flags}])",
        "subtitle_track_template": "{file_name}[ ({flags})]",
    }
)


@REGISTRY.register("naming")
@dataclass(frozen=True, slots=True)
class NamingOptions:
    # The MKV title and the track names; an empty template leaves the title or the names as they are. Empty by
    # default, so a profile renames nothing until a template is set; see `SUGGESTED_TEMPLATES`.
    title_template: str = ""
    video_track_template: str = ""
    audio_track_template: str = ""
    subtitle_track_template: str = ""
    # The user's own tokens, usable in every template; they may not reuse a built-in token's name.
    custom_tokens: list[CustomToken] = field(default_factory=list)
    # Token name -> value read -> text to use instead. Applies to built-in and defined tokens; the default
    # display names (codecs, HDR kinds) are rewritten the same way.
    value_maps: dict[str, dict[str, str]] = field(default_factory=dict)
