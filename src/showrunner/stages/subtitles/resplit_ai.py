"""The re-split step, by timing or with AI. With AI, the model says which of a window's words go on which reference
cue, starting from the timing's cuts: its answer must hold every word of the window once and in order, and moves only
where the cuts fall, so the text comes out as it went in. A window whose answer does not, or that times out, keeps the
timing's cuts. A server or model that is gone sends every window left by timing at once, so the subtitle is still
re-split.

What the AI way did is kept beside the result, written again after each window, so Jobs shows how far it is and the
views read which windows went by timing. Model input, not UI text: the prompt stays in English.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from itertools import accumulate
from pathlib import Path
from typing import ClassVar

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.stages.subtitles.options import Lines
from showrunner.stages.subtitles.prompt import RETRY_TEMPERATURE, TEMPERATURE, numbered
from showrunner.stages.subtitles.resplit import Layout, Tuning, by_timing, plain_words
from showrunner.stages.subtitles.translate import window_settings
from showrunner.stages.subtitles.windows import Window, run_windows, split
from showrunner.stages.subtitles.work import Runner, StepWork
from showrunner.tools.ai import AiError, Backend, ChatAnswer, ChatRequest, ErrorKind, Message, Role

_REPORT = ".resplit.json"
_LABEL = re.compile(r"^\w+:$")
_WINDOWS = "windows"  # the folder beside the result where each window's answer is kept, as translate keeps its own

_SYSTEM = """\
You fix where a {target} subtitle's words are cut between cues, so each cue says what the {source} cue it is timed \
to says.

The user sends numbered cues. Each cue starts with its number in square brackets on a line of its own, like [1], then \
a line starting "{source}:" with what the cue says, then a line starting "{target}:" with the {target} words it has \
now. Answer with the same numbers in the same order, each number in square brackets on a line of its own followed by \
the {target} words that cue should have, and nothing else: no "{target}:" label, no notes, no explanations, no code \
fences.

Rules:
- Only move words between neighbouring cues: a word at the end of a cue may go to the start of the next one, and one \
at the start of a cue to the end of the one before.
- Keep every {target} word exactly once and in the same order, exactly as written: never add, drop, change, \
translate, reorder or repeat a word, and keep each word's punctuation with it.
- Where a cue's words already say what its {source} line says, keep them as they are.
- A cue whose {source} line the {target} text does not say may be left empty after its number.
- Answer every number from [1] to the last, once each."""

_AGAIN = (
    "Your answer did not hold the cues [1] to [{count}] once each and in order, with every word of the text once, "
    "in order and unchanged. Answer again with exactly the cues [1] to [{count}], each number in square brackets on "
    "a line of its own followed by its words, and nothing else."
)


@dataclass(frozen=True, slots=True)
class ResplitReport:
    """What a re-split with AI did, or has done so far, in one subtitle."""

    model: str
    windows: int  # in the whole subtitle
    done: int  # windows answered or gone by timing so far; `windows` once the step ended
    by_timing: tuple[int, ...] = ()  # the windows that kept the timing's cuts, counted from 1
    retried: int = 0  # windows asked a second time, since the first answer could not be used
    reused: int = 0  # windows an earlier run answered

    @property
    def finished(self) -> bool:
        return self.done >= self.windows


def resplit_runner(backend: Callable[[], Backend]) -> Runner:
    """The runner of the re-split step. `backend` is asked at each run with AI, so the backend chosen then is used."""

    def run(work: StepWork, cancel: threading.Event | None) -> None:
        if work.source is None or work.reference is None:
            raise ValueError("re-splitting needs the subtitle and a text reference")
        lines = read_cues(work.source, work.language)
        tuning = Tuning.read(dict(work.step.settings))
        layout = by_timing(lines, read_cues(work.reference, work.reference_language), tuning)
        if work.step.way is Lines.WITH_AI and layout.slots():
            layout = _with_ai(layout, work, _UntilGone(backend()), cancel)
        result = layout.cues()
        # Never written with a word lost or moved; the step fails instead and the subtitle stays as it was synced.
        if _words(result) != _words(lines):
            raise ValueError(f"re-split changed the words of {work.source.name}")
        write_cues(work.output, result, like=work.source, language=work.language)

    return run


def _with_ai(layout: Layout, work: StepWork, backend: Backend, cancel: threading.Event | None) -> Layout:
    slots, references = layout.slots(), layout.slot_references()
    size = window_settings(dict(work.step.settings))[0]
    total = len(split(len(slots), size, 0))
    model, barriers = work.step.model, layout.barriers()
    write_report(work.output, ResplitReport(model, total, 0))

    def ask(cues: Sequence[Cue], window: Window) -> ChatRequest:
        return resplit_request(
            cues, references, window, model=model, source=work.reference_language, target=work.language
        )

    def read(cues: Sequence[Cue], window: Window, text: str) -> Sequence[Cue]:
        return read_split(cues, window, text, barriers)

    def progress(fraction: float) -> None:
        # Only for the views: a report that cannot be written while a view holds it costs nothing.
        with contextlib.suppress(OSError):
            write_report(work.output, ResplitReport(model, total, round(fraction * total)))
        if work.progress is not None:
            work.progress(fraction)

    result = run_windows(
        slots,
        size=size,
        overlap=0,
        ask=ask,
        read=read,
        again=retry_request,
        backend=backend,
        kept=work.output.parent / _WINDOWS,
        cancel=cancel,
        progress=progress,
    )
    by_timing_ = tuple(failure.window.index + 1 for failure in result.failed)
    write_report(work.output, ResplitReport(model, total, total, by_timing_, result.retried, result.reused))
    return layout.with_counts([len(cue.text.split()) for cue in result.cues])


def resplit_request(
    cues: Sequence[Cue],
    references: Sequence[Cue],
    window: Window,
    *,
    model: str,
    source: Language | None,
    target: Language | None,
) -> ChatRequest:
    """The request for a window: its reference cues numbered from 1, each with what the reference says and the words
    the timing gave it. A small model keeps to numbers it is shown words for; given the whole text at once, it numbers
    the text's sentences instead."""
    source_name = source.name if source is not None else "Reference"
    target_name = target.name if target is not None else "Subtitle"
    blocks = [
        f"[{number}]\n{source_name}: {' '.join(plain_words(reference.text))}\n{target_name}: "
        + " ".join(plain_words(cue.text))
        for number, (reference, cue) in enumerate(zip(window.own(references), window.own(cues), strict=True), start=1)
    ]
    system = _SYSTEM.format(source=source_name, target=target_name)
    return ChatRequest(model, system, (Message(Role.USER, "\n".join(blocks)),), temperature=TEMPERATURE)


def retry_request(window: Window, request: ChatRequest, answer: str) -> ChatRequest:
    """The request again, with the answer that could not be used and what was wrong with it after it."""
    note = Message(Role.USER, _AGAIN.format(count=window.end - window.start))
    shown = (Message(Role.ASSISTANT, answer), note) if answer.strip() else (note,)
    return replace(request, messages=(*request.messages, *shown), temperature=RETRY_TEMPERATURE)


def read_split(cues: Sequence[Cue], window: Window, text: str, barriers: frozenset[int]) -> list[Cue]:
    """The window's slots with the words the answer gives each, taken from the slots themselves so their markup stays.
    Raises `ValueError` for an answer whose words, compared exactly, are not the window's in order, or that moves a
    word across a line kept with its own timing."""
    own = window.own(cues)
    answered = [plain_words(" ".join(lines)) for lines in numbered(text, len(own))]
    expected = [_same(word) for cue in own for word in plain_words(cue.text)]
    if [_same(word) for words in answered for word in words] != expected:
        # The label of the request's lines ("Turkish:") echoed before a cue's words is form, not a word.
        answered = [words[1:] if words and _LABEL.match(words[0]) else words for words in answered]
    if [_same(word) for words in answered for word in words] != expected:
        raise ValueError("the answer's words are not the text's, once each and in order")
    counts = [len(words) for words in answered]
    before = [len(cue.text.split()) for cue in own]
    for offset in range(1, len(own)):
        if window.start + offset in barriers and sum(counts[:offset]) != sum(before[:offset]):
            raise ValueError("a word moved across a line kept with its own timing")
    tokens = [token for cue in own for token in cue.text.split()]
    bounds = [0, *accumulate(counts)]
    return [replace(cue, text=" ".join(tokens[a:b])) for cue, a, b in zip(own, bounds, bounds[1:], strict=False)]


def read_report(output: Path) -> ResplitReport | None:
    """What the re-split with AI that writes `output` did, or has done so far; None before it ran, by timing, or when
    lost."""
    try:
        found = json.loads(_report_path(output).read_text(encoding="utf-8"))
        return ResplitReport(**{**found, "by_timing": tuple(found.get("by_timing", ()))})
    except (OSError, ValueError, TypeError):
        return None


def write_report(output: Path, report: ResplitReport) -> None:
    # Written in place, as translate's report is, for the same reason: a view may be reading it.
    _report_path(output).write_text(json.dumps(asdict(report)), encoding="utf-8")


def _report_path(output: Path) -> Path:
    return output.with_name(output.name + _REPORT)


def _words(cues: Sequence[Cue]) -> list[str]:
    return [word for cue in cues for word in plain_words(cue.text)]


def _same(word: str) -> str:
    # The same letters may come back composed another way. No case is folded: a Turkish dotless i is a letter of its
    # own.
    return unicodedata.normalize("NFC", word)


class _UntilGone:
    """The backend until its server or model is gone; from then on every window left costs only itself at once, so
    it goes by timing instead of ending the step."""

    name: ClassVar[str] = "until-gone"

    def __init__(self, backend: Backend) -> None:
        self._backend = backend
        self._gone: AiError | None = None

    def models(self) -> Sequence[str]:
        return self._backend.models()

    def version(self) -> str:
        return self._backend.version()

    def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer:
        if self._gone is None:
            try:
                return self._backend.chat(request, cancel)
            except AiError as error:
                if error.kind in (ErrorKind.TIMEOUT, ErrorKind.BAD_ANSWER):
                    raise
                self._gone = error
        raise AiError(ErrorKind.TIMEOUT, f"gone: {self._gone}")
