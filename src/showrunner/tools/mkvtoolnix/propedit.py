"""`mkvpropedit`: change the title, track names, languages and flags of a Matroska file in place."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from showrunner.core.language import Language
from showrunner.tools.process import ProcessTimeoutError, ProgramNotFoundError, RunResult, run

# mkvpropedit ends with 1 when it only warned, 2 when it could not do the edit.
_ERROR_EXIT_CODE = 2


class Property(StrEnum):
    """The properties the app edits; the values are the names mkvpropedit uses."""

    TITLE = "title"
    NAME = "name"
    # The value is an IETF tag. It is written to the IETF element, which keeps the region and script
    # (`pt-BR`), and to the legacy three-letter element that ffprobe and older players read; setting one
    # element does not update the other when the IETF element is set, so both are written.
    LANGUAGE = "language"
    FLAG_DEFAULT = "flag-default"
    FLAG_FORCED = "flag-forced"
    FLAG_HEARING_IMPAIRED = "flag-hearing-impaired"
    FLAG_COMMENTARY = "flag-commentary"


@dataclass(frozen=True, slots=True)
class Edit:
    """One property set to one value. The title belongs to the file; every other property to a track."""

    prop: Property
    value: str | bool
    track_id: int | None = None  # mkvmerge track ID

    def __post_init__(self) -> None:
        if (self.prop is Property.TITLE) != (self.track_id is None):
            raise ValueError(f"{self.prop.value} {'takes no' if self.track_id is None else 'needs a'} track ID")
        if isinstance(self.value, bool) != self.prop.value.startswith("flag-"):
            raise ValueError(f"wrong kind of value for {self.prop.value}")
        if self.prop is Property.LANGUAGE and Language.parse(str(self.value)) is None:
            raise ValueError(f"{self.value!r} is not a language")


class PropeditError(Exception):
    """mkvpropedit could not make the edit; the message is the program's own."""


def selector(track_id: int) -> str:
    """The `--edit` selector of a track, from the ID the probe stores.

    The probe stores mkvmerge's track ID, which counts from 0 in the order the tracks are listed in the
    file. `track:N` counts the same listing from 1, so it is the ID plus one. The other selectors do not fit:
    `track:@N` takes the Matroska track number, which the probe does not keep and which need not equal the
    position, and `track:=UID` needs the track UID, which it does not keep either.
    """
    return f"track:{track_id + 1}"


def build_arguments(path: Path, edits: Sequence[Edit]) -> list[str]:
    """Everything after the program name: the file, then one `--edit` block per target, in first-seen order."""
    targets: dict[int | None, list[Edit]] = {}
    for edit in edits:
        targets.setdefault(edit.track_id, []).append(edit)
    arguments = [str(path)]
    for track_id, group in targets.items():
        arguments += ["--edit", "info" if track_id is None else selector(track_id)]
        for edit in group:
            if edit.prop is Property.LANGUAGE:
                # The legacy element first: changing it also resets the IETF element to the same code.
                language = Language.parse(str(edit.value))
                assert language is not None  # checked when the edit was made
                arguments += ["--set", f"language={language.alpha3}", "--set", f"language-ietf={edit.value}"]
                continue
            value = ("1" if edit.value else "0") if isinstance(edit.value, bool) else edit.value
            arguments += ["--set", f"{edit.prop.value}={value}"]
    return arguments


def edit_headers(
    mkvpropedit: Path,
    path: Path,
    edits: Sequence[Edit],
    *,
    timeout: float,
    cancel: threading.Event | None = None,
) -> None:
    """Make all edits in one run of mkvpropedit, so the file is opened and written once.

    Raises `PropeditError` when the program fails, cannot be started or runs out of time. Cancellation
    propagates as `ProcessCancelledError`.
    """
    if not edits:
        return
    try:
        result = run([mkvpropedit, *build_arguments(path, edits)], timeout=timeout, cancel=cancel)
    except (ProgramNotFoundError, ProcessTimeoutError) as error:
        raise PropeditError(str(error)) from error
    if result.returncode >= _ERROR_EXIT_CODE:
        raise PropeditError(_message(result))


def _message(result: RunResult) -> str:
    # The program writes its errors to standard output, one `Error:` line per problem.
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("Error:")]
    return "; ".join(errors or lines) or f"exit code {result.returncode}"
