"""Options of the scan stage."""

from __future__ import annotations

from dataclasses import dataclass

from showrunner.core.options.registry import REGISTRY


@REGISTRY.register("scan")
@dataclass(frozen=True, slots=True)
class ScanOptions:
    # Read untagged subtitle files and guess their language from the text.
    detect_untagged_languages: bool = True
    # Treat the files of `Subs` and `Subtitles` folders as belonging to the videos beside the folder.
    subtitle_subfolders: bool = True
