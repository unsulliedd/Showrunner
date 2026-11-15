"""`mkvmerge`: a new Matroska file from chosen tracks of a video and from added files, in a given order."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.track import TrackFlags, TrackKind
from showrunner.tools.process import ProgramNotFoundError, run

# mkvmerge ends with 1 when it only warned, 2 when it could not write the file.
_ERROR_EXIT_CODE = 2
_PROGRESS = re.compile(r"#GUI#progress (\d+)%")
_KIND_OPTIONS = {
    TrackKind.VIDEO: ("--video-tracks", "--no-video"),
    TrackKind.AUDIO: ("--audio-tracks", "--no-audio"),
    TrackKind.SUBTITLE: ("--subtitle-tracks", "--no-subtitles"),
}
# Every flag is passed with its value: mkvmerge otherwise makes an added subtitle track a default track.
_FLAG_OPTIONS = {
    "default": "--default-track-flag",
    "forced": "--forced-display-flag",
    "hearing_impaired": "--hearing-impaired-flag",
    "visual_impaired": "--visual-impaired-flag",
    "commentary": "--commentary-flag",
    "original": "--original-flag",
}
# Warnings that mean subtitle text was not converted to UTF-8, so the new file would hold garbled text.
_ENCODING_WARNINGS = ("iconv", "invalid 8-bit characters")


@dataclass(frozen=True, slots=True)
class OutputTrack:
    """One track of the new file, with every header value it gets."""

    source: int  # index into `Merge.sources`
    track_id: int  # mkvmerge's ID of the track in its source; 0 for a subtitle file
    kind: TrackKind
    name: str
    language: Language | None
    flags: TrackFlags
    # For a text subtitle file: the iconv name of its encoding. Empty leaves it to mkvmerge.
    charset: str = ""


@dataclass(frozen=True, slots=True)
class Merge:
    output: Path
    sources: tuple[Path, ...]  # the video first; its chapters, attachments and tags are copied
    tracks: tuple[OutputTrack, ...]  # in the order of the new file
    title: str


@dataclass(frozen=True, slots=True)
class MergeResult:
    warnings: tuple[str, ...] = ()


class MergeError(Exception):
    """mkvmerge could not write the file; the message is the program's own."""


def iconv_name(codec: str) -> str:
    """mkvmerge's iconv reads `euc-kr` and `shift-jis` but not Python's `euc_kr`."""
    return codec.replace("_", "-")


def build_arguments(merge: Merge) -> list[str]:
    """Everything after the program name. The interface language is English, since messages are matched by
    their words, and GUI mode makes progress one line per step."""
    arguments = ["--ui-language", "en", "--gui-mode", "--output", str(merge.output), "--title", merge.title]
    for index, source in enumerate(merge.sources):
        tracks = [t for t in merge.tracks if t.source == index]
        for kind, (keep, none) in _KIND_OPTIONS.items():
            ids = [str(t.track_id) for t in tracks if t.kind is kind]
            arguments += [keep, ",".join(ids)] if ids else [none]
        for track in tracks:
            tid = track.track_id
            arguments += ["--track-name", f"{tid}:{track.name}"]
            arguments += ["--language", f"{tid}:{track.language.ietf if track.language else 'und'}"]
            for field, option in _FLAG_OPTIONS.items():
                arguments += [option, f"{tid}:{int(getattr(track.flags, field))}"]
            if track.charset:
                arguments += ["--sub-charset", f"{tid}:{track.charset}"]
        arguments.append(str(source))
    arguments += ["--track-order", ",".join(f"{t.source}:{t.track_id}" for t in merge.tracks)]
    return arguments


def merge(
    mkvmerge: Path,
    spec: Merge,
    *,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> MergeResult:
    """Write the new file; `progress` gets the fraction done, from 0 to 1. A large file takes as long as the
    disk needs, so there is no timeout; Cancel stops the program. Raises `MergeError` when mkvmerge fails or
    cannot convert subtitle text; cancellation propagates as `ProcessCancelledError`. A failed run can leave a
    partial output, which the caller removes."""

    def on_line(line: str) -> None:
        if progress is not None and (found := _PROGRESS.match(line)):
            progress(int(found[1]) / 100)

    try:
        result = run([mkvmerge, *build_arguments(spec)], cancel=cancel, on_line=on_line)
    except ProgramNotFoundError as error:
        raise MergeError(str(error)) from error
    errors, warnings = _messages(result.output)
    if result.returncode >= _ERROR_EXIT_CODE:
        raise MergeError("; ".join(errors) or f"exit code {result.returncode}")
    if bad := [w for w in warnings if any(word in w for word in _ENCODING_WARNINGS)]:
        raise MergeError("; ".join(bad))
    return MergeResult(tuple(warnings))


def _messages(output: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for line in output.splitlines():
        line = line.strip()
        for prefix, found in (("#GUI#error ", errors), ("Error: ", errors)):
            if line.startswith(prefix):
                found.append(line.removeprefix(prefix))
        for prefix in ("#GUI#warning ", "Warning: "):
            if line.startswith(prefix):
                warnings.append(line.removeprefix(prefix))
    return errors, warnings
