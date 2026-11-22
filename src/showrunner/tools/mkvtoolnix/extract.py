"""`mkvextract`: one track of a Matroska file written to a file of its own, in the format the codec has outside the
container (SubRip, Advanced SubStation, WebVTT for text, a `.sup` stream for PGS)."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from pathlib import Path

from showrunner.tools.process import ProgramNotFoundError, run

# mkvextract ends with 1 when it only warned, 2 when it could not write the file.
_ERROR_EXIT_CODE = 2
_PROGRESS = re.compile(r"#GUI#progress (\d+)%")


class ExtractError(Exception):
    """mkvextract could not write the track; the message is the program's own."""


def extract_track(
    mkvextract: Path,
    video: Path,
    track_id: int,
    output: Path,
    *,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Write track `track_id` (mkvmerge's ID) of `video` to `output`; `progress` gets the fraction done, from 0 to 1.
    A long picture track takes as long as the disk needs, so there is no timeout; Cancel stops the program. Raises
    `ExtractError` when mkvextract fails; cancellation propagates as `ProcessCancelledError`. A failed run can leave a
    partial output, which the caller removes."""

    def on_line(line: str) -> None:
        if progress is not None and (found := _PROGRESS.match(line)):
            progress(int(found[1]) / 100)

    arguments = ["--ui-language", "en", "--gui-mode", "tracks", str(video), f"{track_id}:{output}"]
    try:
        result = run([mkvextract, *arguments], cancel=cancel, on_line=on_line)
    except ProgramNotFoundError as error:
        raise ExtractError(str(error)) from error
    if result.returncode >= _ERROR_EXIT_CODE:
        errors = [
            line.strip().removeprefix("#GUI#error ").removeprefix("Error: ")
            for line in result.output.splitlines()
            if line.strip().startswith(("#GUI#error ", "Error: "))
        ]
        raise ExtractError("; ".join(errors) or f"exit code {result.returncode}")
