"""The plan for one file: which tracks stay, which go, which flags change. Pure logic, nothing is read or written."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.naming.names import channel_layout, codec_display
from showrunner.core.track import ObjectAudio, SubtitleProperties, Track, TrackFlags, TrackKind
from showrunner.stages.scan.extensions import TEXT_SUBTITLE_EXTENSIONS
from showrunner.stages.tracks.matching import matches
from showrunner.stages.tracks.options import FlagShape, PairedFile, TrackMatch, TrackRule, TracksOptions, Verdict

# Matroska codec IDs of the subtitle formats the scan collects, so codec rules see a subtitle file like a track.
_SUBTITLE_CODECS = {
    ".srt": "S_TEXT/UTF8",
    ".ass": "S_TEXT/ASS",
    ".ssa": "S_TEXT/SSA",
    ".vtt": "S_TEXT/WEBVTT",
    ".sup": "S_HDMV/PGS",
    ".sub": "S_VOBSUB",
    ".idx": "S_VOBSUB",
}


class Flag(StrEnum):
    """The flags a plan changes; the values are the field names of `TrackFlags`."""

    DEFAULT = "default"
    FORCED = "forced"


class PlanProblemKind(StrEnum):
    NO_VIDEO_LEFT = "no-video-left"
    NO_AUDIO_LEFT = "no-audio-left"


@dataclass(frozen=True, slots=True)
class FlagChange:
    flag: Flag
    value: bool


@dataclass(frozen=True, slots=True)
class PlannedTrack:
    """A track that stays. `external` is set for a subtitle file that is added to the video."""

    # For an external subtitle a stand-in with a negative id, as the file has no track number yet.
    track: Track
    external: SubtitleFile | None = None
    flag_changes: tuple[FlagChange, ...] = ()

    @property
    def flags(self) -> TrackFlags:
        """The flags after the changes."""
        return replace(self.track.flags, **{change.flag.value: change.value for change in self.flag_changes})


@dataclass(frozen=True, slots=True)
class DroppedTrack:
    track: Track
    external: SubtitleFile | None
    rule_index: int  # position in `TracksOptions.rules`
    rule: TrackRule


@dataclass(frozen=True, slots=True)
class TrackPlan:
    # In the new file's order: embedded tracks in file order, then the subtitle files in the order they are paired,
    # unless `TracksOptions.order` moves them.
    kept: tuple[PlannedTrack, ...]
    # Tracks the rules drop, and subtitle files they leave out.
    dropped: tuple[DroppedTrack, ...]
    # `kept` is in another order than the one above.
    reordered: bool = False

    @property
    def needs_remux(self) -> bool:
        """True when a track is dropped, a subtitle file is added or the order changes; otherwise only headers
        change."""
        return (
            self.reordered
            or any(d.external is None for d in self.dropped)
            or any(k.external is not None for k in self.kept)
        )


@dataclass(frozen=True, slots=True)
class PlanProblem:
    kind: PlanProblemKind
    dropped: tuple[DroppedTrack, ...]  # every track of that kind, each with the rule that drops it


@dataclass(frozen=True, slots=True)
class PlanRefused:
    """Returned instead of a plan when the rules would leave a file without video or without audio."""

    problems: tuple[PlanProblem, ...]


def describe_track(track: Track) -> str:
    """Kind, codec, channels and language for a message, for example `audio Dolby Digital Plus 5.1 English`."""
    object_audio = track.audio.object_audio if track.audio else ObjectAudio.NONE
    channels = channel_layout(track.audio.channels) if track.audio else ""
    codec = codec_display(track.codec, object_audio)
    language = track.language.name if track.language else ""
    return " ".join(part for part in (track.kind.value, codec, channels, language) if part)


def plan_tracks(item: MediaItem, options: TracksOptions) -> TrackPlan | PlanRefused:
    """Apply the rules to the tracks of the file and to the paired subtitle files chosen to be added."""
    entries: list[tuple[Track, SubtitleFile | None]] = [(track, None) for track in item.file.tracks]
    # A stand-in keeps the number of its place among all paired files, so a choice on one file renumbers no other.
    entries += [
        (stand_in(subtitle, index), subtitle)
        for index, subtitle in enumerate(item.subtitles)
        if PairedFile.of(subtitle) in options.add_paired
    ]
    active = [(index, rule) for index, rule in enumerate(options.rules) if rule.enabled]

    from_names = options.flags_from_names
    kept: list[tuple[Track, SubtitleFile | None]] = []
    dropped: list[DroppedTrack] = []
    for track, external in entries:
        decider = deciding(active, track, from_names)
        if decider and decider[1].verdict is Verdict.DROP:
            dropped.append(DroppedTrack(track, external, *decider))
        else:
            kept.append((track, external))

    if problems := _guard(kept, dropped):
        return PlanRefused(problems)
    in_file_order = kept
    kept = _in_order(kept, options.order, from_names)

    final = [{flag: getattr(track.flags, flag.value) for flag in Flag} for track, _ in kept]
    for flag in Flag:
        for kind in TrackKind:
            of_kind = [n for n, (track, _) in enumerate(kept) if track.kind is kind]
            winner = _first_choice(flag, kind, active, kept, from_names)
            if winner is not None:
                for n in of_kind:
                    final[n][flag] = n == winner
    planned = tuple(
        PlannedTrack(
            track,
            external,
            tuple(
                FlagChange(flag, value) for flag, value in final[n].items() if value != getattr(track.flags, flag.value)
            ),
        )
        for n, (track, external) in enumerate(kept)
    )
    return TrackPlan(planned, tuple(dropped), kept != in_file_order)


def deciding(active: list[tuple[int, TrackRule]], track: Track, from_names: bool) -> tuple[int, TrackRule] | None:
    """The first switched-on rule that keeps or drops `track`, with its place in the rule list: the one that decides
    its fate. `active` holds the switched-on rules with their places."""
    return next(
        (
            (i, rule)
            for i, rule in active
            if rule.verdict is not Verdict.PASS and matches(rule.match, track, flags_from_name=from_names)
        ),
        None,
    )


def _in_order(
    kept: list[tuple[Track, SubtitleFile | None]], order: list[TrackMatch], from_names: bool
) -> list[tuple[Track, SubtitleFile | None]]:
    """`kept` in the order `TracksOptions.order` describes."""
    if not order:
        return kept
    ranks = [
        next((n for n, match in enumerate(order) if matches(match, track, flags_from_name=from_names)), len(order))
        for track, _ in kept
    ]
    return [kept[n] for n in order_places([track.kind for track, _ in kept], ranks)]


def order_places(kinds: Sequence[TrackKind], ranks: Sequence[int]) -> list[int]:
    """For each place of a list of tracks, the index of the track that takes it: each kind's tracks are sorted into
    the places that kind holds, by rank, and tracks of one rank keep their order. A kind never takes another's place,
    so video stays ahead of audio whatever the ranks say."""
    result = list(range(len(kinds)))
    for kind in dict.fromkeys(kinds):
        places = [n for n, k in enumerate(kinds) if k is kind]
        for place, source in zip(places, sorted(places, key=ranks.__getitem__), strict=True):
            result[place] = source
    return result


def _first_choice(
    flag: Flag,
    kind: TrackKind,
    active: list[tuple[int, TrackRule]],
    kept: list[tuple[Track, SubtitleFile | None]],
    from_names: bool,
) -> int | None:
    """Index into `kept`, which is in the new file's order, of the track the first fitting `first` rule picks for
    this kind."""
    for _, rule in active:
        if getattr(rule, flag.value) is not FlagShape.FIRST:
            continue
        for n, (track, _) in enumerate(kept):
            if track.kind is kind and matches(rule.match, track, flags_from_name=from_names):
                return n
    return None


def _guard(kept: list[tuple[Track, SubtitleFile | None]], dropped: list[DroppedTrack]) -> tuple[PlanProblem, ...]:
    problems = []
    required = ((TrackKind.VIDEO, PlanProblemKind.NO_VIDEO_LEFT), (TrackKind.AUDIO, PlanProblemKind.NO_AUDIO_LEFT))
    for kind, problem in required:
        gone = tuple(d for d in dropped if d.track.kind is kind)
        if gone and not any(track.kind is kind for track, _ in kept):
            problems.append(PlanProblem(problem, gone))
    return tuple(problems)


def stand_in(subtitle: SubtitleFile, index: int) -> Track:
    """The track a paired subtitle file is planned as: its place among the paired files gives a negative id."""
    suffix = Path(subtitle.path).suffix.casefold()
    return Track(
        id=-(index + 1),
        kind=TrackKind.SUBTITLE,
        codec=_SUBTITLE_CODECS.get(suffix, ""),
        language=subtitle.language,
        flags=TrackFlags(forced=subtitle.forced, hearing_impaired=subtitle.sdh),
        subtitle=SubtitleProperties(text_based=suffix in TEXT_SUBTITLE_EXTENSIONS),
    )
