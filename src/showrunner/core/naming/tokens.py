"""The tokens a template can use and how each one is read from a file.

This table is the one place that documents the built-in tokens: `example` is a typical value. A token that
cannot be read (no such track, value unknown) is empty, which makes an optional group around it disappear.
The user's own tokens (`custom.py`) sit beside these and cannot reuse their names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from showrunner.core.media import Episode, Extra, MediaItem, Movie
from showrunner.core.naming.custom import CustomToken
from showrunner.core.naming.names import (
    OBJECT_AUDIO_NAMES,
    channel_layout,
    codec_display,
    guess_source_of,
    hdr_display,
    resolution,
)
from showrunner.core.naming.style import EpisodeCodeFormat, SpaceStyle, episode_code
from showrunner.core.track import ObjectAudio, Track, TrackKind, flags_with_name


class Scope(StrEnum):
    ITEM = "item"  # the movie or episode and its file
    VIDEO = "video"  # the video track: the track being named, else the file's first one
    TRACK = "track"  # the track being named; empty when a name is made for the file itself


@dataclass(frozen=True, slots=True)
class NamingContext:
    """Everything a template reads: the item, the track being named and the user's choices."""

    item: MediaItem
    track: Track | None = None
    # The source set for the batch; empty means it is guessed from the file name and its folders.
    source: str = ""
    # The user's own tokens and value maps (token name -> value read -> text to use).
    custom: Sequence[CustomToken] = ()
    value_maps: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    # `{flags}` also names the flags the track's name implies, as the track rules read them.
    flags_from_names: bool = True
    # How tokens are written: what every space of the name becomes (typed gaps and spaces inside values), and the
    # spelling of `{episode_code}`.
    space: SpaceStyle = SpaceStyle.SPACE
    episode_code_format: EpisodeCodeFormat = EpisodeCodeFormat.UPPER
    # The title the file gets, for `{file_title}`; None in the title template, which has no title to copy.
    file_title: str | None = None

    @property
    def video(self) -> Track | None:
        if self.track and self.track.kind is TrackKind.VIDEO:
            return self.track
        return next(iter(self.item.file.video_tracks), None)

    @property
    def object_audio(self) -> ObjectAudio:
        audio = self.track.audio if self.track else None
        return audio.object_audio if audio else ObjectAudio.NONE


@dataclass(frozen=True, slots=True)
class Token:
    name: str
    scope: Scope
    example: str
    read: Callable[[NamingContext], str | int | None]
    # Numbers accept a zero-padding format such as `{season:00}`; text does not.
    numeric: bool = False
    # Usable in the track templates only; the title template reports it.
    track_templates_only: bool = False
    # False for a value that is copied as it is: the template's join choice does not touch its spaces.
    joined: bool = True


def _show(c: NamingContext) -> str | None:
    identity = c.item.identity
    return identity.show if isinstance(identity, Episode | Extra) else None


def _movie(c: NamingContext) -> str | None:
    identity = c.item.identity
    return identity.title if isinstance(identity, Movie) else None


def _title(c: NamingContext) -> str | None:
    return _show(c) or _movie(c)


def _episode(c: NamingContext) -> Episode | None:
    identity = c.item.identity
    return identity if isinstance(identity, Episode) else None


def _season(c: NamingContext) -> int | None:
    return episode.season if (episode := _episode(c)) else None


def _episode_number(c: NamingContext) -> int | None:
    return episode.episode if (episode := _episode(c)) else None


def _episode_code(c: NamingContext) -> str | None:
    if (episode := _episode(c)) is None:
        return None
    return episode_code(c.episode_code_format, episode.season, episode.episode, episode.last_episode)


def _episode_title(c: NamingContext) -> str | None:
    identity = c.item.identity
    if isinstance(identity, Extra):
        return identity.title  # the nearest thing an extra has to an episode title
    return episode.episode_title if (episode := _episode(c)) else None


def _source(c: NamingContext) -> str:
    return c.source or guess_source_of(c.item.file.path)


def _resolution(c: NamingContext) -> str | None:
    video = c.video.video if c.video else None
    return resolution(video.width, video.height) if video else None


def _hdr(c: NamingContext) -> str | None:
    video = c.video.video if c.video else None
    return hdr_display(video.hdr) if video else None


def _video_codec(c: NamingContext) -> str | None:
    return codec_display(c.video.codec, ObjectAudio.NONE) if c.video else None


def _bit_depth(c: NamingContext) -> int | None:
    video = c.video.video if c.video else None
    return video.bit_depth if video else None


def _codec(c: NamingContext) -> str | None:
    return codec_display(c.track.codec, c.object_audio) if c.track else None


def _channels(c: NamingContext) -> str | None:
    audio = c.track.audio if c.track else None
    return channel_layout(audio.channels) if audio else None


def _object_audio(c: NamingContext) -> str | None:
    return OBJECT_AUDIO_NAMES.get(c.object_audio)


def _language(c: NamingContext) -> str | None:
    return c.track.language.name if c.track and c.track.language else None


def _language_code(c: NamingContext) -> str | None:
    return c.track.language.ietf if c.track and c.track.language else None


def _track_name(c: NamingContext) -> str | None:
    return c.track.name if c.track else None


# Default is left out: it is about which track a player picks, not about what the track holds.
_FLAG_NAMES = (
    ("forced", "Forced"),
    ("hearing_impaired", "SDH"),
    ("visual_impaired", "Visual Impaired"),
    ("commentary", "Commentary"),
    ("original", "Original"),
)


def _flags(c: NamingContext) -> str | None:
    if not c.track:
        return None
    flags = flags_with_name(c.track) if c.flags_from_names else c.track.flags
    return " ".join(label for attribute, label in _FLAG_NAMES if getattr(flags, attribute))


_TOKENS = (
    Token("show", Scope.ITEM, "Show Name", _show),
    Token("movie", Scope.ITEM, "Movie Title", _movie),
    # The show of an episode, the title of a movie: one token for a template that serves both.
    Token("title", Scope.ITEM, "Show Name", _title),
    Token("year", Scope.ITEM, "2020", lambda c: c.item.identity.year, numeric=True),
    Token("season", Scope.ITEM, "1", _season, numeric=True),
    Token("episode", Scope.ITEM, "5", _episode_number, numeric=True),
    # `S01E01`, or `S01E01-E02` for a file of two episodes; the spelling is the naming option `episode_code_format`.
    Token("episode_code", Scope.ITEM, "S01E05", _episode_code),
    Token("episode_title", Scope.ITEM, "Episode Name", _episode_title),
    # The file's base name: no folder, no extension.
    Token("file_name", Scope.ITEM, "Show Name (2020) - 1x05 - Episode Name", lambda c: c.item.file.path.stem),
    # Set for the batch, else guessed from the file name, else from the folders above it, nearest first
    # (BluRay, WEB-DL, WEBRip, HDTV, DVD, with Hybrid and REMUX markers), else empty.
    Token("source", Scope.ITEM, "Hybrid WEB-DL", _source),
    Token("resolution", Scope.VIDEO, "1080p", _resolution),
    # `HDR`, `HDR10+`, `HDR/DV` or `HLG`; a value map renames them. Empty for SDR.
    Token("hdr", Scope.VIDEO, "HDR/DV", _hdr),
    Token("video_codec", Scope.VIDEO, "HEVC", _video_codec),
    Token("bit_depth", Scope.VIDEO, "10", _bit_depth, numeric=True),
    # The codec's display name, with object audio folded in: `Dolby Atmos`, `Dolby Digital Plus`.
    Token("codec", Scope.TRACK, "Dolby Digital Plus", _codec),
    Token("channels", Scope.TRACK, "5.1", _channels),
    Token("object_audio", Scope.TRACK, "Dolby Atmos", _object_audio),
    Token("atmos", Scope.TRACK, "Dolby Atmos", _object_audio),  # same as object_audio, for the common case
    Token("language", Scope.TRACK, "Turkish", _language),
    Token("language_code", Scope.TRACK, "tr", _language_code),
    Token("track_name", Scope.TRACK, "Original Name", _track_name),
    Token("flags", Scope.TRACK, "Forced", _flags),
    # The title the file gets from the title template, else the title it has; `{title}` is the show's or the movie's.
    Token(
        "file_title",
        Scope.TRACK,
        "Show Name - 1x05 - Episode Name",
        lambda c: c.file_title,
        track_templates_only=True,
        joined=False,
    ),
)

TOKENS: dict[str, Token] = {token.name: token for token in _TOKENS}
