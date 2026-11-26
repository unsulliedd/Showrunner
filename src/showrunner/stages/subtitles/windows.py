"""AI work on a subtitle in windows of cues, so a failure costs one window and a resume skips the finished ones.

A window answers for its own cues; the cues before it (`overlap`) go along as context only, so the model reads each
line in its scene while every cue is answered once. Each finished window's answer is kept under a name made of the
whole request (the model, the prompt, its cues and their context), so a rerun with the same input reuses it and a
changed cue, prompt or model asks again. A window whose answer times out or cannot be read keeps its cues as they are
and is named in the result; it is not kept, so the next run asks for it again. A server that stops or a model that is
gone ends the work instead: every later window would fail the same way, and the windows kept so far stay for the
resume.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from showrunner.core.cue import Cue
from showrunner.tools.ai import AiError, Backend, ChatRequest, ErrorKind
from showrunner.tools.process import ProcessCancelledError

# What costs only the window; every other error ends the work.
_WINDOW_ERRORS = (ErrorKind.TIMEOUT, ErrorKind.BAD_ANSWER)


@dataclass(frozen=True, slots=True)
class Window:
    index: int
    start: int  # the first cue it answers for
    end: int  # past the last cue it answers for
    context: int  # the first cue sent before `start` as context

    def own(self, cues: Sequence[Cue]) -> Sequence[Cue]:
        return cues[self.start : self.end]

    def before(self, cues: Sequence[Cue]) -> Sequence[Cue]:
        return cues[self.context : self.start]


@dataclass(frozen=True, slots=True)
class WindowFailure:
    window: Window
    kind: ErrorKind
    detail: str


@dataclass(frozen=True, slots=True)
class WindowRun:
    cues: tuple[Cue, ...]  # every window's answer in order, a failed window's own cues as they were
    failed: tuple[WindowFailure, ...]
    reused: int  # windows answered by an earlier run


# The request for one window, made from all the cues and the window. Its whole content names the kept answer.
type Ask = Callable[[Sequence[Cue], Window], ChatRequest]
# The cues a window's answer stands for; raises `ValueError` (or `AiError`) for an answer that cannot be read.
type Read = Callable[[Sequence[Cue], Window, str], Sequence[Cue]]


def split(count: int, size: int, overlap: int) -> list[Window]:
    """`count` cues in windows of `size`, each with up to `overlap` cues before it as context."""
    if size < 1 or not 0 <= overlap < size:
        raise ValueError(f"windows of {size} with {overlap} before them")
    return [
        Window(index, start, min(start + size, count), max(start - overlap, 0))
        for index, start in enumerate(range(0, count, size))
    ]


def run_windows(
    cues: Sequence[Cue],
    *,
    size: int,
    overlap: int,
    ask: Ask,
    read: Read,
    backend: Backend,
    kept: Path,
    cancel: threading.Event | None = None,
    progress: Callable[[float], None] | None = None,
) -> WindowRun:
    """Each window through `backend`, one after the other, the answers kept in the folder `kept`. Raises
    `ProcessCancelledError` on a cancel between or during windows, and `AiError` when the server or the model is
    gone."""
    windows = split(len(cues), size, overlap)
    answered: list[Cue] = []
    failed: list[WindowFailure] = []
    reused = 0
    for window in windows:
        if cancel is not None and cancel.is_set():
            raise ProcessCancelledError("cancelled", ())
        request = ask(cues, window)
        path = kept / f"{_digest(request)}.txt"
        result = _reuse(path, cues, window, read)
        if result is not None:
            reused += 1
        else:
            try:
                text = backend.chat(request, cancel).text
                result = read(cues, window, text)
            except AiError as error:
                if error.kind not in _WINDOW_ERRORS:
                    raise
                failed.append(WindowFailure(window, error.kind, error.detail))
            except ValueError as error:
                failed.append(WindowFailure(window, ErrorKind.BAD_ANSWER, str(error)))
            else:
                _keep(path, text)
        answered.extend(result if result is not None else window.own(cues))
        if progress is not None:
            progress((window.index + 1) / len(windows))
    return WindowRun(tuple(answered), tuple(failed), reused)


def _reuse(path: Path, cues: Sequence[Cue], window: Window, read: Read) -> Sequence[Cue] | None:
    """The kept answer of the same request, read again; None when there is none or it no longer reads."""
    try:
        return read(cues, window, path.read_text(encoding="utf-8"))
    except (OSError, ValueError, AiError):
        return None


def _keep(path: Path, text: str) -> None:
    """Written whole or not at all, so a crash in the middle never leaves half an answer to reuse."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


def _digest(request: ChatRequest) -> str:
    # The timeout does not change the answer, so it is left out of the name.
    made_of = (request.model, request.system, request.messages)
    return hashlib.blake2b(repr(made_of).encode("utf-8"), digest_size=16).hexdigest()
