"""Options of the mux stage: what happens to the original after a remux, and what the new file is called."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from showrunner.core.options.registry import REGISTRY


class Original(StrEnum):
    """Where the original goes once the new file is written and checked. Either way it is never deleted."""

    RECYCLE = "recycle"  # the Windows Recycle Bin
    KEEP = "keep"  # `keep_folder`, beside the video


class NameField(StrEnum):
    KEEP_FOLDER = "keep_folder"
    SUFFIX = "suffix"


@REGISTRY.register("mux")
@dataclass(frozen=True, slots=True)
class MuxOptions:
    original: Original = Original.RECYCLE
    # A folder beside the video for kept originals and the subtitle files the remux added. A dot name keeps it out
    # of the next scan, so a kept original is not read as a second copy of the episode.
    keep_folder: str = ".originals"
    # Added to the new file's name before `.mkv`; empty gives it the original's name.
    suffix: str = ""


# Characters Windows does not allow in a file name.
_FORBIDDEN = set('<>:"/\\|?*')


def check_names(options: MuxOptions) -> tuple[NameField, ...]:
    """The fields that cannot be part of a file name. The keep folder is checked only while originals are kept,
    since nothing reads it otherwise."""
    bad = []
    folder = options.keep_folder.strip()
    # Windows drops a dot or space at the end of a folder name, so such a name would not be the folder asked for.
    if options.original is Original.KEEP and (
        not folder or folder in {".", ".."} or not _allowed(folder) or folder.endswith((".", " "))
    ):
        bad.append(NameField.KEEP_FOLDER)
    if not _allowed(options.suffix):
        bad.append(NameField.SUFFIX)
    return tuple(bad)


def _allowed(text: str) -> bool:
    return not any(ch in _FORBIDDEN or ord(ch) < 32 for ch in text)
