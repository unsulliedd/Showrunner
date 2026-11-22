"""Timed subtitle lines, and SubRip, Advanced SubStation and WebVTT files read and written as lists of them."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pysubs2

from showrunner.core.encoding import decode_text
from showrunner.core.language import Language

# The pysubs2 format of each file extension the subtitle stage reads and writes.
FORMATS = {".srt": "srt", ".ass": "ass", ".ssa": "ssa", ".vtt": "vtt"}
_STYLED = {"ass", "ssa"}
_DEFAULT_STYLE = "Default"


@dataclass(frozen=True, slots=True)
class Cue:
    start: float  # seconds
    end: float
    # Line breaks as "\n"; styling as Advanced SubStation override tags (`{\i1}`), which a SubRip or WebVTT file gets
    # back as its own tags when written.
    text: str
    style: str = ""  # the Advanced SubStation style; empty for the other formats

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2


def read_cues(path: Path, language: Language | None = None) -> list[Cue]:
    """The dialogue lines of a subtitle file in the order the file holds them; comment lines are not cues. The text
    encoding is detected, `language` deciding a legacy code page. Raises OSError when the file cannot be read and
    ValueError when it is not a subtitle of its extension's format. Not called by the app yet; the subtitle engines
    read their input with it."""
    format_ = _format(path)
    subtitle = _load(path, format_, language)
    styled = format_ in _STYLED
    return [
        Cue(event.start / 1000, event.end / 1000, event.text.replace(r"\N", "\n"), event.style if styled else "")
        for event in subtitle.events
        if not event.is_comment
    ]


def write_cues(path: Path, cues: Iterable[Cue], *, like: Path | None = None, language: Language | None = None) -> None:
    """Write the cues as UTF-8 in the format of the path's extension. `like` is the file they were read from: an
    Advanced SubStation result keeps its styles and script info, which cues do not carry. Raises OSError and
    ValueError as `read_cues` does. Not called by the app yet; the subtitle engines write their results with it."""
    format_ = _format(path)
    subtitle = _load(like, _format(like), language) if like is not None else pysubs2.SSAFile()
    subtitle.events = [
        pysubs2.SSAEvent(
            start=round(cue.start * 1000),
            end=round(cue.end * 1000),
            text=cue.text.replace("\n", r"\N"),
            style=cue.style or _DEFAULT_STYLE,
        )
        for cue in cues
    ]
    path.write_bytes(subtitle.to_string(format_).encode("utf-8"))


def _format(path: Path) -> str:
    try:
        return FORMATS[path.suffix.casefold()]
    except KeyError:
        raise ValueError(f"not a text subtitle format: {path.suffix or path.name}") from None


def _load(path: Path, format_: str, language: Language | None) -> pysubs2.SSAFile:
    # pysubs2 reads a string as it is, so Windows line ends would stay inside the cue text.
    text = decode_text(path.read_bytes(), language).replace("\r\n", "\n").replace("\r", "\n")
    try:
        return pysubs2.SSAFile.from_string(text, format_=format_)
    except pysubs2.Pysubs2Error as error:
        raise ValueError(f"{path.name}: {error}") from error
