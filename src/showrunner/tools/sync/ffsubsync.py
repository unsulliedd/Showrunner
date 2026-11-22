"""The ffsubsync adapter: one global shift (and, where the frame rate differs, a stretch) found by correlating the
speech of the reference with the lines of the subtitle.

ffsubsync runs in a child process of its own (`ffsubsync_worker`), started through the one place programs are run, so
Cancel stops it and its library loads in the child, never in the app. Against a reference subtitle it needs nothing
else; against the audio it needs ffmpeg, which the adapter is given the path of.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import ClassVar

from showrunner.core.cue import read_cues
from showrunner.core.encoding import detect_encoding
from showrunner.tools.process import ProgramNotFoundError, run
from showrunner.tools.sync.base import (
    IN_SYNC_BELOW,
    UNSURE_BELOW,
    Setting,
    SettingKind,
    SyncError,
    SyncOutcome,
    SyncRequest,
)

NAME = "ffsubsync"
# ffsubsync samples speech at this many values a second; its score is the sum of agreements over them.
SAMPLE_RATE = 100
_PROGRAM = "showrunner.tools.sync.ffsubsync_worker"
_FRAME_RATE_OFF = "off"
_VAD = "webrtc"
_SETTINGS = (
    Setting("max_offset", SettingKind.NUMBER, "60"),  # seconds searched either way
    Setting("framerate", SettingKind.CHOICE, "", (_FRAME_RATE_OFF,)),  # empty tries the usual frame rate changes
    # ffsubsync's own default takes the video's subtitle track as the speech when it has one, which is a track of
    # the file that need not be in the subtitle's language or timing; the default here always listens to the audio.
    Setting("vad", SettingKind.CHOICE, _VAD, ("auditok",)),
)


class FfsubsyncAdapter:
    name: ClassVar[str] = NAME
    settings: ClassVar[tuple[Setting, ...]] = _SETTINGS
    # Measured on real files (docs/design/m3/SYNC.md): a subtitle that was in time measured at most 0.21 s from the
    # reference, one that was 0.4 s off at 0.48 s or more; scores of results that were right ranged from 0.05 to 0.75.
    defaults: ClassVar[dict[str, str]] = {IN_SYNC_BELOW: "0.3", UNSURE_BELOW: "0.1"}

    @staticmethod
    def available() -> bool:
        """Whether ffsubsync is installed in the interpreter that runs the app."""
        return importlib.util.find_spec("ffsubsync") is not None

    def __init__(self, ffmpeg: Path | None = None) -> None:
        self._ffmpeg = ffmpeg
        self.audio = ffmpeg is not None

    def sync(self, request: SyncRequest) -> SyncOutcome:
        """Raises `SyncError` where ffsubsync fails or the audio is asked for without ffmpeg; Cancel ends it with
        `ProcessCancelledError`."""
        if request.reference is None and self._ffmpeg is None:
            raise SyncError("syncing to the audio needs ffmpeg")
        reference = request.reference or request.video
        language = request.language
        cues = read_cues(request.subtitle, language)
        length = max((cue.end for cue in cues), default=0.0)
        if length <= 0:
            raise SyncError(f"{request.subtitle.name}: no line to sync")
        arguments = [
            str(reference),
            "-i",
            str(request.subtitle),
            "-o",
            str(request.output),
            "--encoding",
            detect_encoding(request.subtitle.read_bytes(), language),
            *self._options(request),
        ]
        found: dict[str, object] = {}
        failures: list[str] = []

        def on_line(line: str) -> None:
            kind, _, rest = line.partition(" ")
            if kind == "progress" and request.progress is not None:
                request.progress(float(rest))
            elif kind == "result":
                found.update(json.loads(rest))
            elif kind == "error":
                failures.append(rest)

        try:
            result = run(
                [sys.executable, "-m", _PROGRAM, *arguments],
                cancel=request.cancel,
                on_line=on_line,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except ProgramNotFoundError as error:
            raise SyncError(str(error)) from error
        if result.returncode != 0 or not found:
            raise SyncError("; ".join(failures) or f"{NAME} ended with exit code {result.returncode}")
        score = float(found["score"])  # type: ignore[arg-type]
        return SyncOutcome(
            offset=float(found["offset"]),  # type: ignore[arg-type]
            scale=float(found["scale"]),  # type: ignore[arg-type]
            # The best the sum can be is one agreement for every sample of the subtitle.
            score=score / (length * SAMPLE_RATE),
            unsure=not found["ok"],
            length=length,
        )

    def _options(self, request: SyncRequest) -> list[str]:
        settings = request.settings
        options = ["--output-encoding", "utf-8"]
        if self._ffmpeg is not None:
            options += ["--ffmpeg-path", str(self._ffmpeg)]
        if settings.get("max_offset"):
            options += ["--max-offset-seconds", settings["max_offset"]]
        if settings.get("framerate") == _FRAME_RATE_OFF:
            options.append("--no-fix-framerate")
        if request.reference is None:
            options += ["--vad", settings.get("vad") or _VAD]
        return options
