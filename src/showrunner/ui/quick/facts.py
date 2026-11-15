"""Text the window shows about a batch and about past folders, built from library items and dates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from showrunner.app.batches.batch import BatchKey, BatchKind
from showrunner.core.media import Episode, MediaItem, Movie
from showrunner.core.naming.names import codec_display, hdr_display, resolution
from showrunner.core.track import ObjectAudio, TrackKind
from showrunner.ui.i18n.catalog import tr, tr_plural
from showrunner.ui.sheet.format import movie_name, size_text


@dataclass(frozen=True, slots=True)
class Heading:
    over: str  # the small line above the title
    title: str
    facts: str


def video_summary(item: MediaItem) -> str:
    """`2160p HEVC HDR/DV` from the first video track; empty without one."""
    track = next((t for t in item.file.tracks if t.kind is TrackKind.VIDEO and t.video is not None), None)
    if track is None or track.video is None:
        return ""
    video = track.video
    parts = (
        resolution(video.width, video.height),
        codec_display(track.codec, ObjectAudio.NONE),
        hdr_display(video.hdr),
    )
    return " ".join(part for part in parts if part)


def duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    hours, minutes = divmod(minutes, 60)
    return tr("facts.duration_hours", hours=hours, minutes=minutes) if hours else tr("facts.duration", minutes=minutes)


def _joined(parts: Sequence[str]) -> str:
    return f" {tr('status.separator')} ".join(part for part in parts if part)


def heading(key: BatchKey, items: Sequence[MediaItem]) -> Heading:
    """The workspace header of a batch: what it belongs to, its name, and a line of facts."""
    summaries = Counter(summary for item in items if (summary := video_summary(item)))
    common = summaries.most_common(1)[0][0] if summaries else ""
    size = size_text(sum(item.file.size for item in items)) if items else ""
    show = key.title if key.year is None else tr("library.movie", title=key.title, year=key.year)
    if key.kind is BatchKind.SEASON:
        count = tr_plural("facts.episodes", len(items))
        return Heading(show, tr("library.season", number=key.season), _joined((count, common, size)))
    if key.kind is BatchKind.SHOW:
        seasons = len({i.identity.season for i in items if isinstance(i.identity, Episode)})
        count = (tr_plural("facts.seasons", seasons), tr_plural("facts.episodes", len(items)))
        return Heading(tr("workspace.over.show"), show, _joined((*count, common, size)))
    if key.kind is BatchKind.MOVIE and len(items) == 1 and isinstance(items[0].identity, Movie):
        movie, file = items[0].identity, items[0].file
        year = str(movie.year) if movie.year else ""
        length = duration(file.duration) if file.duration else ""
        return Heading(tr("workspace.over.movie"), movie.title, _joined((year, length, common, size)))
    titles = [movie_name(i.identity) for i in items if isinstance(i.identity, Movie)]
    title = tr("library.movies") if len(titles) == len(items) else tr("workspace.selection")
    return Heading(tr("workspace.over.selection"), title, _joined((tr_plural("facts.videos", len(items)), size)))


def when(opened: str, now: datetime) -> str:
    """How long ago an ISO date and time was, in words; empty when it cannot be read."""
    try:
        then = datetime.fromisoformat(opened)
    except ValueError:
        return ""
    days = (now.date() - then.date()).days
    if days <= 0:
        return tr("time.today")
    if days == 1:
        return tr("time.yesterday")
    if days < 7:
        return tr_plural("time.days", days)
    if days < 14:
        return tr("time.last_week")
    if days < 31:
        return tr_plural("time.weeks", days // 7)
    if days < 62:
        return tr("time.last_month")
    if days < 365:
        return tr_plural("time.months", days // 30)
    return tr("time.long_ago")
