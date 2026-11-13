"""Pairing subtitle files with videos by title first and episode number second.

File names in one folder often disagree: `Show (1992) S03E04 Snowfall.mkv` sits beside
`Show - 305 - Snowfall.tr.srt`, because the video follows the airing order and the subtitle the
production order. A matching title therefore outweighs a matching number.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from showrunner.stages.scan.names import episode_code, match_tokens

_MIN_TITLE_RATIO = 0.6
_SAME_CODE_BONUS = 0.5
# A word in at least this share of a folder's names is the show name or a release tag, not the title.
_COMMON_SHARE = 0.6


@dataclass(frozen=True, slots=True)
class NameKey:
    code: tuple[int, int] | None  # season and episode
    title: str  # what is left of the name once the words common to the folder are removed


@dataclass(frozen=True, slots=True)
class Match:
    """Indexes into the lists given to `pair`. `alternatives` scored exactly as high as `subtitle`."""

    video: int
    subtitle: int
    alternatives: tuple[int, ...] = ()


def name_keys(names: Sequence[str]) -> list[NameKey]:
    """Keys for the names of one folder, which decides what counts as common."""
    # Names that repeat, such as the files of one episode in several languages, count once; otherwise the
    # words of a single movie would be common to its own files.
    unique = {name: match_tokens(name) for name in names}
    counts = Counter(word for words in unique.values() for word in set(words))
    # Two names cannot tell what is common: with fewer than three, nothing is dropped.
    limit = len(unique) * _COMMON_SHARE if len(unique) >= 3 else len(unique) + 1
    return [
        NameKey(episode_code(name), " ".join(word for word in unique[name] if counts[word] < limit)) for name in names
    ]


def _score(video: NameKey, subtitle: NameKey) -> float:
    ratio = SequenceMatcher(None, video.title, subtitle.title).ratio() if video.title and subtitle.title else 0.0
    same_code = video.code is not None and video.code == subtitle.code
    if ratio < _MIN_TITLE_RATIO and not same_code:
        return 0.0
    # A matching number adds to a weak title match, so it still beats a stranger whose title is merely close.
    return ratio + (_SAME_CODE_BONUS if same_code else 0.0)


def pair(videos: Sequence[NameKey], subtitles: Sequence[NameKey], sizes: Sequence[int]) -> list[Match]:
    """Greedy best-first: the highest score is settled first, and a subtitle goes to at most one video.

    Of equal scores the larger subtitle file wins. Videos without a match are left out.
    """
    scored = sorted(
        (
            (_score(video, subtitle), sizes[si], -vi, -si)
            for vi, video in enumerate(videos)
            for si, subtitle in enumerate(subtitles)
        ),
        reverse=True,
    )
    chosen: dict[int, tuple[int, float]] = {}
    alternatives: dict[int, list[int]] = {}
    used: set[int] = set()
    for score, _size, neg_vi, neg_si in scored:
        if score <= 0:
            break
        vi, si = -neg_vi, -neg_si
        if si in used:
            continue
        if vi not in chosen:
            chosen[vi] = (si, score)
            used.add(si)
        elif math.isclose(score, chosen[vi][1]):
            alternatives.setdefault(vi, []).append(si)
    # A subtitle that went to another video later is not an alternative here.
    return [
        Match(vi, si, tuple(a for a in alternatives.get(vi, []) if a not in used))
        for vi, (si, _score_) in sorted(chosen.items())
    ]
