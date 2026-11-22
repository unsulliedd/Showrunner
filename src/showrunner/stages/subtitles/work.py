"""What one step of subtitle work is given to run: the engines that carry the steps out take a `StepWork`."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.track import Track
from showrunner.stages.subtitles.plan import Step


@dataclass(frozen=True, slots=True)
class StepWork:
    step: Step
    video: Path
    # The subtitle the step works on: the paired file or the previous step's result. None for a step that reads the
    # video: the reference, an embedded track, or a translation, which starts from the reference.
    source: Path | None
    reference: Path | None  # the reference as read, for the steps that work against it; None for the audio
    language: (
        Language | None
    )  # of the finished subtitle: the rules to clean it with, the legacy code page it is read in
    track: Track | None  # for a step that reads one out of the video
    output: Path  # where the step writes its result, in the format of its extension
    # Takes the fraction of the step done, from 0 to 1, for a step that takes long enough to show it.
    progress: Callable[[float], None] | None = field(default=None, compare=False)


# Runs one step, writing `output`; raises on failure. Called on a background thread.
type Runner = Callable[[StepWork, threading.Event | None], None]
