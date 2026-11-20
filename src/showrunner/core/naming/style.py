"""How a template writes its names: the character every space becomes, and the episode code."""

from __future__ import annotations

from enum import StrEnum


class SpaceStyle(StrEnum):
    """What a template joins its words with: each space of the name, whether typed or inside a value. Any other typed
    character is never changed."""

    SPACE = "space"
    DOT = "dot"
    UNDERSCORE = "underscore"
    DASH = "dash"

    @property
    def character(self) -> str:
        return _CHARACTERS[self]


_CHARACTERS = {SpaceStyle.SPACE: " ", SpaceStyle.DOT: ".", SpaceStyle.UNDERSCORE: "_", SpaceStyle.DASH: "-"}


class EpisodeCodeFormat(StrEnum):
    """The spellings of `{episode_code}`; each value is the code of season 1, episode 1 in that spelling."""

    UPPER = "S01E01"
    LOWER = "s01e01"
    SHORT_SEASON = "S1E01"
    CROSS = "1x01"
    SHORT_E = "1e01"


# Per format: the text before the season, its width, the text before the episode and the text before the last
# episode of a file that holds several. `1x01-02` rather than `1x01-1x02`: Kodi reads a dash and a number after
# an episode as one more episode, but would read the second `1x` of `1x01-1x02` as episode 1 again.
_SHAPES = {
    EpisodeCodeFormat.UPPER: ("S", 2, "E", "-E"),
    EpisodeCodeFormat.LOWER: ("s", 2, "e", "-e"),
    EpisodeCodeFormat.SHORT_SEASON: ("S", 1, "E", "-E"),
    EpisodeCodeFormat.CROSS: ("", 1, "x", "-"),
    EpisodeCodeFormat.SHORT_E: ("", 1, "e", "-e"),
}


def episode_code(style: EpisodeCodeFormat, season: int, first: int, last: int | None = None) -> str:
    """The code of an episode, `S01E01`; a file holding episodes `first` to `last` reads `S01E01-E02`."""
    lead, width, mark, tail = _SHAPES[style]
    code = f"{lead}{season:0{width}d}{mark}{first:02d}"
    return f"{code}{tail}{last:02d}" if last is not None and last > first else code
