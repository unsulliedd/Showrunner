"""What every AI backend shares: the chat request it is given, the answer it gives, and how it fails.

The shapes follow the OpenAI chat API (a system prompt, then messages with a role and content), which both Ollama and a
llama.cpp server speak, so a second backend is one more class behind `Backend`.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatRequest:
    model: str
    system: str
    messages: tuple[Message, ...]
    # Seconds the whole answer may take, a cold start of the model included.
    timeout: float = 300.0


@dataclass(frozen=True, slots=True)
class ChatAnswer:
    text: str
    seconds: float  # from sending the request to the last word of the answer


class ErrorKind(StrEnum):
    UNREACHABLE = "unreachable"  # no server answers at the backend's address
    MODEL_MISSING = "model-missing"  # the server has no model of the requested name
    TIMEOUT = "timeout"  # the answer did not come in time
    BAD_ANSWER = "bad-answer"  # the server answered, but with an error or something unreadable


class AiError(Exception):
    def __init__(self, kind: ErrorKind, detail: str = "") -> None:
        super().__init__(f"{kind.value}: {detail}" if detail else kind.value)
        self.kind = kind
        self.detail = detail


class Backend(Protocol):
    """One local AI server. Called on a background thread; Cancel stops a chat by `cancel` and raises
    `ProcessCancelledError`, as it stops a program."""

    name: ClassVar[str]  # the backend's id, as its dependency entry names it

    def models(self) -> Sequence[str]:
        """The installed models, sorted. Answers fast: a server that does not answer at once raises
        `AiError(UNREACHABLE)`, so this is also the check that the server is up."""
        ...

    def version(self) -> str:
        """The server's version, answered as fast as `models`; raises `AiError` as it does."""
        ...

    def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer: ...
