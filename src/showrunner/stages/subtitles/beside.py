"""Finished subtitles written beside the video: what they are named, and how one takes its place without harming the
file it replaces.

A subtitle is copied from its kept result to a hidden name in the target's folder, read back as cues, and only then
given its name. A replaced subtitle goes to the Recycle Bin between the check and the rename, so a run that stops at any
point leaves the original either in place or in the Recycle Bin with the checked copy beside it.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path

from showrunner.core.cue import Cue, read_cues
from showrunner.core.language import Language
from showrunner.stages.scan.names import parse_subtitle_name
from showrunner.tools.recycle import recycle as shell_recycle

type Recycle = Callable[[Sequence[Path]], None]

# Marks the name a subtitle is written and checked under; the dot name keeps it out of a scan, and the extension
# stays, since reading it back as cues goes by the extension.
_PARTIAL = ".showrunner-partial"


def new_file_name(name: str, text: str) -> str:
    """`Show.S01E01.tr.forced.srt` with `_cleaned` gives `Show.S01E01_cleaned.tr.forced.srt`: the text goes before
    the language and flag words, so a scan still reads them; a name without them gets it before the extension."""
    base = parse_subtitle_name(name).base
    return f"{base}{text}{name[len(base) :]}"


def is_result(name: str, text: str) -> bool:
    """Whether the file was named with the new-file text, so it is a result of an earlier run and not worked on
    again."""
    return bool(text) and parse_subtitle_name(name).base.casefold().endswith(text.casefold())


def language_name(
    stem: str, language: Language | None, format_: str, *, forced: bool = False, sdh: bool = False
) -> str:
    """The name of a subtitle with no file of its own, beside the video `stem`: `Show.S01E01.tr.srt`, with the flag
    words a scan reads back (`Show.S01E01.en.sdh.srt`), so two tracks of one language get two names."""
    words = [language.ietf] if language is not None else []
    words += [word for word, on in (("forced", forced), ("sdh", sdh)) if on]
    return ".".join((stem, *words, format_))


def partial_path(target: Path) -> Path:
    return target.with_name(f".{target.stem}{_PARTIAL}{target.suffix}")


class BesideFailure(StrEnum):
    EXISTS = "beside-exists"  # a file of the target's name lies there and holds something else
    CHECK = "beside-check"  # the copy did not read back as the result
    RECYCLE = "beside-recycle"  # the replaced file could not go to the Recycle Bin, so it stays and nothing is written
    WRITE = "beside-write"  # the copy or the rename failed


class BesideError(OSError):
    def __init__(self, failure: BesideFailure, detail: str) -> None:
        super().__init__(f"{failure.value}: {detail}")
        self.failure = failure
        self.detail = detail


def finish_replace(target: Path) -> bool:
    """Give a replacing subtitle its name when a run stopped after the original went to the Recycle Bin: the copy
    beside it passed its check before that, so only the rename was left. False when there is nothing to finish."""
    partial = partial_path(target)
    if target.exists() or not partial.is_file():
        return False
    partial.rename(target)
    return True


def write_beside(
    result: Path, target: Path, language: Language | None, *, replaces: bool, recycle: Recycle = shell_recycle
) -> None:
    """Write the kept `result` to `target`. A file already at `target` is replaced only with `replaces`, after the copy
    is checked; one that already reads as the result is left as it is (a run that stopped before it was recorded, or a
    cleanup that changed nothing). Raises `BesideError`; the file at `target` is untouched unless it went to the Recycle
    Bin."""
    wanted = read_cues(result, language)
    if target.exists():
        if _reads_as(target, wanted, language):
            partial_path(target).unlink(missing_ok=True)
            return
        if not replaces:
            raise BesideError(BesideFailure.EXISTS, target.name)
    partial = partial_path(target)
    recycled = False
    try:
        try:
            shutil.copyfile(result, partial)
        except OSError as error:
            raise BesideError(BesideFailure.WRITE, str(error)) from error
        if not _reads_as(partial, wanted, language):
            raise BesideError(BesideFailure.CHECK, target.name)
        if replaces and target.exists():
            try:
                recycle([target])
            except OSError as error:
                raise BesideError(BesideFailure.RECYCLE, str(error)) from error
            recycled = True
        # Checked again: on Windows a rename refuses a file in the way, elsewhere it would replace it.
        if target.exists():
            raise BesideError(BesideFailure.EXISTS, target.name)
        try:
            partial.rename(target)
        except OSError as error:
            raise BesideError(BesideFailure.WRITE, str(error)) from error
    except BesideError:
        # Once the original is in the Recycle Bin the checked copy is the only one in place, so it stays for a resume.
        if not recycled:
            partial.unlink(missing_ok=True)
        raise


def _reads_as(path: Path, wanted: list[Cue], language: Language | None) -> bool:
    try:
        return read_cues(path, language) == wanted
    except Exception:  # a file that cannot be read as a subtitle does not hold the result
        return False
