"""The file kinds the scan recognizes."""

from __future__ import annotations

VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts", ".webm", ".wmv"})

SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sup", ".sub", ".idx"})

# The formats whose text can be read to detect a language; the others are images or need their `.idx` file.
TEXT_SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt"})

# Folders that release packs put subtitle files in, beside the videos.
SUBTITLE_FOLDER_NAMES = frozenset({"subs", "subtitles", "sub", "subtitle"})

# Folder names, in lower case, that hold the extras of a show or movie: Plex's extras folders and the common
# release-pack names for them.
EXTRAS_FOLDER_NAMES = frozenset(
    {
        "extras",
        "extra",
        "featurettes",
        "featurette",
        "deleted scenes",
        "deleted scene",
        "behind the scenes",
        "interviews",
        "interview",
        "trailers",
        "trailer",
        "scenes",
        "shorts",
        "other",
        "bonus",
        "bonus features",
    }
)
