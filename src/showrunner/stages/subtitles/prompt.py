"""What a translation asks the model, and how its answer is read back into cues. Model input, not UI text: the words
stay here, in English, whatever language the window is in.

A window is sent as numbered blocks, one per cue, each line of a cue on a line of its own, so the model sees and keeps
the reference's line breaks. The cues before and after the window go along as context, marked as not to translate and
without numbers, so the model never answers them. An answer must hold the same numbers in the same order; one that
does not cannot be read, which costs the window a retry and then the window. The temperature is 0: the same window
gives the same words on every run, and a free choice of words was seen to turn a negation around.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace

from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.stages.subtitles.windows import Window
from showrunner.tools.ai import ChatRequest, Message, Role

TEMPERATURE = 0.0
# The retry of an unreadable answer: a little freedom, so it is not the same answer again.
RETRY_TEMPERATURE = 0.3
DEFAULT_WINDOW = 40
DEFAULT_CONTEXT = 5

_SYSTEM = """\
You translate the subtitles of films and TV shows {direction}.

The user sends numbered cues. Each cue starts with its number in square brackets on a line of its own, like [1], \
followed by the cue's text. Answer with the same cues in the same order, each number in square brackets on a line of \
its own followed by the translation of that cue, and nothing else: no notes, no explanations, no code fences.

Rules:
- Translate every numbered cue, one translation per number. Never merge, split, skip or reorder cues, even when a \
sentence runs on from one cue into the next.
- Keep the line breaks of each cue: a cue of two lines is translated into two lines. A line that starts with "-" is \
another speaker and stays a line of its own, starting with "-".
- Keep markup exactly as it is, around the words it belongs to: tags such as <i>, </i>, <b>, <u>, <font ...> and \
codes in curly braces such as {{\\an8}}.
- Keep the names of people, places and brands as they are.
- Keep the register of the dialogue: casual speech stays casual, rude stays rude, formal stays formal. Choose the \
familiar or the polite form of address from the scene.
- Translate the meaning, not word for word, in natural spoken {target}; keep each line about as short as the original.
- Lines marked as context are there to help you understand the scene. Never translate or answer them."""

_BEFORE = "Earlier lines, context only, not to translate:"
_AFTER = "Later lines, context only, not to translate:"
_CUES = "Translate these cues:"
_AGAIN = (
    "Your answer did not hold the cues [1] to [{count}] once each and in order. Answer again with exactly the cues "
    "[1] to [{count}], each number in square brackets on a line of its own followed by its translation, and nothing "
    "else."
)

_NUMBER = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
_FENCE = re.compile(r"^\s*```")


def system_prompt(source: Language | None, target: Language) -> str:
    direction = f"from {source.name} into {target.name}" if source is not None else f"into {target.name}"
    return _SYSTEM.format(direction=direction, target=target.name)


def window_text(cues: Sequence[Cue], window: Window, context: int) -> str:
    """The user's message for a window: the context before it, its own cues numbered from 1, the context after it."""
    parts = []
    if before := window.before(cues):
        parts.append("\n".join([_BEFORE, *(_context_line(cue) for cue in before)]))
    own = [f"[{number}]\n{cue.text}" for number, cue in enumerate(window.own(cues), start=1)]
    parts.append("\n".join([_CUES, *own]))
    if after := cues[window.end : window.end + context]:
        parts.append("\n".join([_AFTER, *(_context_line(cue) for cue in after)]))
    return "\n\n".join(parts)


def translate_request(
    cues: Sequence[Cue], window: Window, *, model: str, source: Language | None, target: Language, context: int
) -> ChatRequest:
    message = Message(Role.USER, window_text(cues, window, context))
    return ChatRequest(model, system_prompt(source, target), (message,), temperature=TEMPERATURE)


def retry_request(window: Window, request: ChatRequest, answer: str) -> ChatRequest:
    """The request again, with the answer that could not be read and what was wrong with it after it."""
    count = window.end - window.start
    note = Message(Role.USER, _AGAIN.format(count=count))
    shown = (Message(Role.ASSISTANT, answer), note) if answer.strip() else (note,)
    return replace(request, messages=(*request.messages, *shown), temperature=RETRY_TEMPERATURE)


def read_answer(cues: Sequence[Cue], window: Window, text: str) -> list[Cue]:
    """The window's own cues with the answer's text and their own timing. Lenient on form (blank lines, code fences,
    the translation on the number's own line), strict on the numbers: each of 1 to the window's count, once and in
    order; raises `ValueError` otherwise. A cue the answer leaves empty keeps its own text: the model found nothing to
    translate in it (a sound, a garbled line), and losing the whole window for it would cost every other line."""
    own = window.own(cues)
    found: list[tuple[int, list[str]]] = []
    for line in text.splitlines():
        if _FENCE.match(line):
            continue
        if (numbered := _NUMBER.match(line)) is not None:
            found.append((int(numbered.group(1)), [numbered.group(2)] if numbered.group(2).strip() else []))
        elif found:
            found[-1][1].append(line)
    numbers = [number for number, _ in found]
    if numbers != list(range(1, len(own) + 1)):
        raise ValueError(f"cues {numbers} for 1 to {len(own)}")
    return [
        replace(cue, text="\n".join(line.strip() for line in lines if line.strip()) or cue.text)
        for cue, (_, lines) in zip(own, found, strict=True)
    ]


def _context_line(cue: Cue) -> str:
    return "> " + " ".join(line.strip() for line in cue.text.splitlines() if line.strip())
