"""Whether a track fits a rule's match."""

from __future__ import annotations

import re
from functools import lru_cache

from showrunner.core.language import Language
from showrunner.core.naming.names import codec_display
from showrunner.core.track import ObjectAudio, Track, flags_with_name
from showrunner.stages.tracks.options import FlagTest, KindTest, SourceTest, TrackMatch

_FLAGS = ("default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original")

NO_LANGUAGE = "und"


def is_paired(track: Track) -> bool:
    """Whether the track stands in for a paired subtitle file beside the video (`stand_in` gives it a negative id,
    as the file has no track number in the video yet)."""
    return track.id < 0


def matches(match: TrackMatch, track: Track, *, flags_from_name: bool = True) -> bool:
    """True when the track passes every test the match sets. With `flags_from_name`, a flag the track's
    name implies (a track named "Commentary" counts as commentary) is tested as set."""
    if match.kind is not KindTest.ANY and match.kind.value != track.kind.value:
        return False
    if match.source is not SourceTest.ANY and (match.source is SourceTest.PAIRED) is not is_paired(track):
        return False
    flags = flags_with_name(track) if flags_from_name else track.flags
    for flag in _FLAGS:
        test = getattr(match, flag)
        if test is not FlagTest.ANY and getattr(flags, flag) is not (test is FlagTest.SET):
            return False
    return (
        _language_fits(match.languages, track.language)
        and _codec_fits(match.codecs, track)
        and _channels_fit(match, track)
        and _name_fits(match, track.name)
    )


def _language_fits(tags: list[str], language: Language | None) -> bool:
    if not tags:
        return True
    for tag in tags:
        if tag.strip().casefold() == NO_LANGUAGE:
            if language is None:
                return True
            continue
        wanted = Language.parse(tag)
        if wanted is None or language is None:
            continue
        if (
            wanted.alpha3 == language.alpha3
            and wanted.region in (None, language.region)
            and wanted.script in (None, language.script)
            and wanted.rest in ("", language.rest)
        ):
            return True
    return False


def _codec_fits(codecs: list[str], track: Track) -> bool:
    wanted = {entry.strip().casefold() for entry in codecs} - {""}
    if not wanted:
        return True
    object_audio = track.audio.object_audio if track.audio else ObjectAudio.NONE
    # A rule for "DTS" fits DTS:X as well, since the plain name is among the names of such a track.
    names = {track.codec, codec_display(track.codec, ObjectAudio.NONE), codec_display(track.codec, object_audio)}
    return not wanted.isdisjoint(name.casefold() for name in names)


def _channels_fit(match: TrackMatch, track: Track) -> bool:
    if not match.min_channels and not match.max_channels:
        return True
    channels = track.audio.channels if track.audio else None
    if channels is None:
        return False
    return channels >= match.min_channels and (not match.max_channels or channels <= match.max_channels)


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _name_fits(match: TrackMatch, name: str) -> bool:
    if not match.name:
        return True
    if match.name_is_regex:
        compiled = _compile(match.name)
        return compiled is not None and compiled.search(name) is not None
    return match.name.casefold() in name.casefold()
