"""Window work: each window through the backend, its answer kept, a failure costing only its window."""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from showrunner.core.cue import Cue
from showrunner.stages.subtitles.windows import Window, WindowRun, run_windows, split
from showrunner.tools.ai import AiError, ChatAnswer, ChatRequest, ErrorKind, Message, Role
from showrunner.tools.process import ProcessCancelledError

CUES = [Cue(float(n), n + 0.5, f"line {n}") for n in range(10)]


def ask(cues: Sequence[Cue], window: Window) -> ChatRequest:
    """The window's own lines after its context, one per line, the context marked."""
    context = [f"> {cue.text}" for cue in window.before(cues)]
    own = [cue.text for cue in window.own(cues)]
    return ChatRequest("sample:9b", "Upper-case each line.", (Message(Role.USER, "\n".join([*context, *own])),))


def read(cues: Sequence[Cue], window: Window, text: str) -> list[Cue]:
    answer = text.split("\n")
    own = window.own(cues)
    if len(answer) != len(own):
        raise ValueError(f"{len(answer)} lines for {len(own)}")
    return [Cue(cue.start, cue.end, line) for cue, line in zip(own, answer, strict=True)]


class Backend:
    """Upper-cases the lines it is sent without the context; fails the windows whose first line is in `fail`."""

    name = "fake"

    def __init__(self, fail: dict[str, AiError | str] | None = None) -> None:
        self.fail = fail or {}
        self.asked: list[str] = []
        self.cancel_after: int | None = None
        self.cancel: threading.Event | None = None

    def models(self) -> list[str]:
        return ["sample:9b"]

    def version(self) -> str:
        return "0"

    def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer:
        own = [line for line in request.messages[0].content.split("\n") if not line.startswith("> ")]
        self.asked.append(own[0])
        if self.cancel is not None and len(self.asked) == self.cancel_after:
            self.cancel.set()
        failure = self.fail.get(own[0])
        if isinstance(failure, AiError):
            raise failure
        if failure is not None:
            return ChatAnswer(failure, 0.1)
        return ChatAnswer("\n".join(line.upper() for line in own), 0.1)


def test_windows_cover_every_cue_once_with_the_cues_before_them_as_context() -> None:
    assert split(10, 4, 1) == [Window(0, 0, 4, 0), Window(1, 4, 8, 3), Window(2, 8, 10, 7)]
    assert split(0, 4, 1) == []
    for size, overlap in ((0, 0), (4, 4), (4, -1)):
        with pytest.raises(ValueError, match="windows"):
            split(10, size, overlap)


def run(backend: Backend, kept: Path, **given: Any) -> WindowRun:
    return run_windows(CUES, size=4, overlap=1, ask=ask, read=read, backend=backend, kept=kept, **given)


def test_every_window_is_answered_in_order_and_reports_its_progress(tmp_path: Path) -> None:
    done: list[float] = []
    result = run(Backend(), tmp_path, progress=done.append)
    assert [cue.text for cue in result.cues] == [f"LINE {n}" for n in range(10)]
    assert [cue.start for cue in result.cues] == [cue.start for cue in CUES]
    assert result.failed == ()
    assert done == pytest.approx([1 / 3, 2 / 3, 1])


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        (AiError(ErrorKind.TIMEOUT, "300 s"), ErrorKind.TIMEOUT),
        (AiError(ErrorKind.BAD_ANSWER, "500: out of memory"), ErrorKind.BAD_ANSWER),
        ("one line for four", ErrorKind.BAD_ANSWER),  # an answer the caller cannot read
    ],
)
def test_a_failed_window_keeps_its_cues_as_they_are_and_costs_only_itself(
    tmp_path: Path, failure: AiError | str, kind: ErrorKind
) -> None:
    result = run(Backend({"line 4": failure}), tmp_path)
    texts = [cue.text for cue in result.cues]
    assert texts == ["LINE 0", "LINE 1", "LINE 2", "LINE 3", "line 4", "line 5", "line 6", "line 7", "LINE 8", "LINE 9"]
    [failed] = result.failed
    assert (failed.window.index, failed.kind) == (1, kind)


def test_a_rerun_reuses_the_finished_windows_and_asks_again_for_the_failed_one(tmp_path: Path) -> None:
    run(Backend({"line 4": AiError(ErrorKind.TIMEOUT)}), tmp_path)
    again = Backend()
    result = run(again, tmp_path)
    assert again.asked == ["line 4"]
    assert result.reused == 2
    assert [cue.text for cue in result.cues] == [f"LINE {n}" for n in range(10)]


def test_a_changed_cue_asks_again_for_its_window_only(tmp_path: Path) -> None:
    run(Backend(), tmp_path)
    changed = [*CUES[:9], Cue(9.0, 9.5, "line nine")]
    again = Backend()
    run_windows(changed, size=4, overlap=1, ask=ask, read=read, backend=again, kept=tmp_path)
    assert again.asked == ["line 8"]


@pytest.mark.parametrize("kind", [ErrorKind.UNREACHABLE, ErrorKind.MODEL_MISSING])
def test_a_gone_server_or_model_ends_the_work_and_the_finished_windows_stay_for_the_resume(
    tmp_path: Path, kind: ErrorKind
) -> None:
    with pytest.raises(AiError) as raised:
        run(Backend({"line 4": AiError(kind)}), tmp_path)
    assert raised.value.kind is kind
    again = Backend()
    run(again, tmp_path)
    assert again.asked == ["line 4", "line 8"]


def test_cancel_stops_between_windows(tmp_path: Path) -> None:
    backend = Backend()
    backend.cancel, backend.cancel_after = threading.Event(), 1
    with pytest.raises(ProcessCancelledError):
        run(backend, tmp_path, cancel=backend.cancel)
    assert backend.asked == ["line 0"]
    # The window answered before the cancel is kept.
    again = Backend()
    run(again, tmp_path)
    assert again.asked == ["line 4", "line 8"]


def test_cancel_during_a_window_reaches_the_backend(tmp_path: Path) -> None:
    class Cancelled(Backend):
        def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer:
            assert cancel is given
            raise ProcessCancelledError("cancelled", ())

    given = threading.Event()
    with pytest.raises(ProcessCancelledError):
        run(Cancelled(), tmp_path, cancel=given)
    assert list(tmp_path.iterdir()) == []


def again(window: Window, request: ChatRequest, answer: str) -> ChatRequest:
    """The first request with a note after it, so a fake that fails on the first line answers the second time."""
    note = Message(Role.USER, f"> {len(window.own(CUES))} lines, please")
    return dataclasses.replace(request, messages=(*request.messages, note), temperature=0.2)


class Picky(Backend):
    """Answers one line too few for a window asked the first time, and as asked once a note follows."""

    def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer:
        answer = super().chat(request, cancel)
        return answer if len(request.messages) > 1 else ChatAnswer(answer.text.rsplit("\n", 1)[0], 0.1)


def test_an_unreadable_answer_is_asked_once_more_and_kept_under_the_first_request(tmp_path: Path) -> None:
    result = run(Picky(), tmp_path, again=again)
    assert [cue.text for cue in result.cues] == [f"LINE {n}" for n in range(10)]
    assert (result.failed, result.retried) == ((), 3)
    # The kept answers are found by the first requests, so a rerun asks nothing.
    rerun = Backend()
    assert run(rerun, tmp_path, again=again).reused == 3
    assert rerun.asked == []


def test_a_window_still_unreadable_after_the_retry_falls_back_and_a_timeout_is_not_retried(tmp_path: Path) -> None:
    backend = Backend({"line 4": "one line for four", "line 8": AiError(ErrorKind.TIMEOUT)})
    result = run(backend, tmp_path, again=again)
    assert [(f.window.index, f.kind) for f in result.failed] == [(1, ErrorKind.BAD_ANSWER), (2, ErrorKind.TIMEOUT)]
    assert result.retried == 1
    assert backend.asked == ["line 0", "line 4", "line 4", "line 8"]


def test_the_temperature_is_part_of_the_kept_answer_s_name(tmp_path: Path) -> None:
    run(Backend(), tmp_path)

    def warmer(cues: Sequence[Cue], window: Window) -> ChatRequest:
        return dataclasses.replace(ask(cues, window), temperature=0.7)

    rerun = Backend()
    run_windows(CUES, size=4, overlap=1, ask=warmer, read=read, backend=rerun, kept=tmp_path)
    assert len(rerun.asked) == 3
