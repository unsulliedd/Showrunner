"""The translate step: the reference, cleaned for its own language, translated window by window into the finished
subtitle's language, each cue keeping the reference's timing. What the step did is kept beside its result, written
again after each window, so Jobs shows how far it is and a resumed job and the views read what fell back.

A window that falls back keeps the reference's text, so the file still gets a whole subtitle, marked as needing review;
one where every window fell back is no translation, and the step fails instead.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.stages.subtitles.prompt import (
    DEFAULT_CONTEXT,
    DEFAULT_WINDOW,
    read_answer,
    retry_request,
    translate_request,
)
from showrunner.stages.subtitles.windows import Window, run_windows, split
from showrunner.stages.subtitles.work import Runner, StepWork
from showrunner.tools.ai import Backend, ChatRequest
from showrunner.tools.cleanit import RuleBook, clean_cues, kept_cues

# The message of a translate step whose every window fell back: "not-translated: <windows>".
NOT_TRANSLATED = "not-translated"
# The step settings a plan writes into a translate step.
WINDOW = "window"
CONTEXT = "context"
_REPORT = ".translate.json"
_WINDOWS = "windows"  # the folder beside the result where each window's answer is kept


@dataclass(frozen=True, slots=True)
class TranslateReport:
    """What a translate step did, or has done so far, in one subtitle."""

    model: str
    windows: int  # in the whole subtitle
    done: int  # windows answered or fallen back so far; `windows` once the step ended
    fell_back: tuple[int, ...] = ()  # the windows that kept the reference's text, counted from 1
    retried: int = 0  # windows asked a second time, since the first answer could not be read
    reused: int = 0  # windows an earlier run answered

    @property
    def finished(self) -> bool:
        return self.done >= self.windows

    @property
    def needs_review(self) -> bool:
        return bool(self.fell_back)


def window_settings(settings: Mapping[str, str]) -> tuple[int, int]:
    """The lines a window answers for and the context lines sent before and after it, from the step's settings; the
    defaults where one is missing or out of range."""
    size = _whole(settings.get(WINDOW), DEFAULT_WINDOW, low=1)
    context = _whole(settings.get(CONTEXT), DEFAULT_CONTEXT, low=0)
    return size, min(context, size - 1)


def translate_runner(backend: Callable[[], Backend], book: Callable[[], RuleBook]) -> Runner:
    """The runner of the translate step. `backend` and `book` are asked at each run, so the backend chosen then and the
    rules the files hold then are used."""

    def run(work: StepWork, cancel: threading.Event | None) -> None:
        if work.reference is None or work.language is None:
            raise ValueError("translating needs a reference and the language to translate into")
        source = work.reference_language
        cues: list[Cue] = read_cues(work.reference, source)
        if work.step.sets:
            cues = kept_cues(clean_cues(cues, book().compile(work.step.sets, source)))
        size, context = window_settings(dict(work.step.settings))
        total = len(split(len(cues), size, context))
        model, target = work.step.model, work.language
        write_report(work.output, TranslateReport(model, total, 0))

        def ask(all_cues: Sequence[Cue], window: Window) -> ChatRequest:
            return translate_request(all_cues, window, model=model, source=source, target=target, context=context)

        def progress(fraction: float) -> None:
            # Only for the views: a report that cannot be written while a view holds it costs nothing.
            with contextlib.suppress(OSError):
                write_report(work.output, TranslateReport(model, total, round(fraction * total)))
            if work.progress is not None:
                work.progress(fraction)

        result = run_windows(
            cues,
            size=size,
            overlap=context,
            ask=ask,
            read=read_answer,
            again=retry_request,
            backend=backend(),
            kept=work.output.parent / _WINDOWS,
            cancel=cancel,
            progress=progress,
        )
        fell_back = tuple(failure.window.index + 1 for failure in result.failed)
        write_report(work.output, TranslateReport(model, total, total, fell_back, result.retried, result.reused))
        if total and len(fell_back) == total:
            raise TranslateError(f"{NOT_TRANSLATED}: {total}")
        write_cues(work.output, result.cues, language=target)

    return run


class TranslateError(Exception):
    pass


def read_report(output: Path) -> TranslateReport | None:
    """What the translate step that writes `output` did, or has done so far; None before it ran or when lost."""
    try:
        found = json.loads(_report_path(output).read_text(encoding="utf-8"))
        return TranslateReport(**{**found, "fell_back": tuple(found.get("fell_back", ()))})
    except (OSError, ValueError, TypeError):
        return None


def write_report(output: Path, report: TranslateReport) -> None:
    # Written in place: on Windows a file replaced while a view reads it raises, and a view reading half a report
    # sees none, which `read_report` already allows.
    _report_path(output).write_text(json.dumps(asdict(report)), encoding="utf-8")


def _report_path(output: Path) -> Path:
    return output.with_name(output.name + _REPORT)


def _whole(text: str | None, default: int, *, low: int) -> int:
    try:
        value = int(text) if text else default
    except ValueError:
        return default
    return value if value >= low else default
