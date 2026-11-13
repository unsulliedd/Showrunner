"""Running ffprobe."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from showrunner.tools.process import run

# Packets, not frames: enough for the decoder to deliver the first few frames of an HEVC stream.
_FIRST_PACKETS = "%+#10"


class FfprobeError(Exception):
    """ffprobe could not read the file or wrote output that is not JSON."""


def read_streams(ffprobe: Path, path: Path, *, timeout: float, cancel: threading.Event | None = None) -> dict[str, Any]:
    """Container, streams and chapters of a file as ffprobe's JSON."""
    return _json(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", path],
        timeout,
        cancel,
    )


def read_first_frames(
    ffprobe: Path, path: Path, stream_index: int, *, timeout: float, cancel: threading.Event | None = None
) -> dict[str, Any]:
    """The first few decoded frames of one stream, with their side data."""
    return _json(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-select_streams",
            str(stream_index),
            "-read_intervals",
            _FIRST_PACKETS,
            "-show_frames",
            path,
        ],
        timeout,
        cancel,
    )


def _json(args: list[str | Path], timeout: float, cancel: threading.Event | None) -> dict[str, Any]:
    result = run(args, timeout=timeout, cancel=cancel)
    if result.returncode != 0:
        raise FfprobeError(result.stderr.strip() or f"exit code {result.returncode}")
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise FfprobeError("output is not JSON") from error
