"""Ollama, through its server's HTTP API. The `ollama` command is never run: on Windows it starts the desktop app."""

from __future__ import annotations

import http.client
import json
import select
import threading
import time
from typing import Any, ClassVar
from urllib.parse import urlsplit

from showrunner.tools.ai.base import AiError, ChatAnswer, ChatRequest, ErrorKind
from showrunner.tools.process import ProcessCancelledError

DEFAULT_URL = "http://127.0.0.1:11434"
# A server on this machine answers a connection at once; a stopped one may take a second to refuse on Windows, which
# shows as a connect timeout rather than a refusal.
CONNECT_SECONDS = 1.0
LIST_SECONDS = 5.0  # the model list, once connected
_CANCEL_POLL_SECONDS = 0.1
_ERROR_LIMIT = 500  # characters of a server's error kept in the message


class OllamaBackend:
    name: ClassVar[str] = "ollama"

    def __init__(self, url: str = DEFAULT_URL) -> None:
        parts = urlsplit(url)
        self._host = parts.hostname or "127.0.0.1"
        self._port = parts.port or 11434

    def models(self) -> list[str]:
        try:
            return sorted(str(model["name"]) for model in self._get("/api/tags")["models"])
        except (KeyError, TypeError) as error:
            raise AiError(ErrorKind.BAD_ANSWER, f"model list: {error}") from error

    def version(self) -> str:
        try:
            return str(self._get("/api/version")["version"])
        except (KeyError, TypeError) as error:
            raise AiError(ErrorKind.BAD_ANSWER, f"version: {error}") from error

    def _get(self, path: str) -> Any:
        """A small JSON document from the server, read with the short timeouts."""
        connection = self._connect(LIST_SECONDS)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            data = _json(response.read())
            if response.status != 200:
                raise AiError(ErrorKind.BAD_ANSWER, _error_text(data, response.status))
            return data
        except TimeoutError as error:
            raise AiError(ErrorKind.TIMEOUT, path) from error
        except OSError as error:
            raise AiError(ErrorKind.UNREACHABLE, str(error)) from error
        finally:
            connection.close()

    def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer:
        """Streamed, so a cancel or the overall timeout is seen between the words of the answer, and while the server
        is silent before its first word (loading the model, reading the prompt)."""
        body = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                *({"role": m.role.value, "content": m.content} for m in request.messages),
            ],
            "stream": True,
            # A thinking model would otherwise write thousands of words of reasoning before each short answer.
            "think": False,
        }
        started = time.monotonic()
        connection = self._connect(request.timeout)
        parts: list[str] = []
        try:
            connection.request("POST", "/api/chat", json.dumps(body), {"Content-Type": "application/json"})
            _wait_for_answer(connection, cancel, started + request.timeout)
            response = connection.getresponse()
            if response.status != 200:
                data = _json(response.read())
                text = _error_text(data, response.status)
                kind = ErrorKind.MODEL_MISSING if response.status == 404 else ErrorKind.BAD_ANSWER
                raise AiError(kind, text)
            for line in response:
                _check_cancel(cancel)
                if time.monotonic() - started > request.timeout:
                    raise AiError(ErrorKind.TIMEOUT, f"{request.timeout:g} s")
                if not line.strip():
                    continue
                chunk = _json(line)
                if "error" in chunk:
                    raise AiError(ErrorKind.BAD_ANSWER, str(chunk["error"])[:_ERROR_LIMIT])
                parts.append(str(chunk.get("message", {}).get("content", "")))
                if chunk.get("done"):
                    if chunk.get("done_reason", "stop") != "stop":
                        # Cut off at the model's context or answer length: the end of the answer is missing.
                        raise AiError(ErrorKind.BAD_ANSWER, f"stopped: {chunk.get('done_reason')}")
                    return ChatAnswer("".join(parts), time.monotonic() - started)
            raise AiError(ErrorKind.BAD_ANSWER, "the answer ended early")
        except (AttributeError, TypeError) as error:
            raise AiError(ErrorKind.BAD_ANSWER, str(error)) from error
        except TimeoutError as error:
            raise AiError(ErrorKind.TIMEOUT, f"{request.timeout:g} s") from error
        except (OSError, http.client.HTTPException) as error:
            raise AiError(ErrorKind.UNREACHABLE, str(error)) from error
        finally:
            connection.close()

    def _connect(self, read_seconds: float) -> http.client.HTTPConnection:
        """A connection opened with the short connect timeout, then given `read_seconds` for each read."""
        connection = http.client.HTTPConnection(self._host, self._port, timeout=CONNECT_SECONDS)
        try:
            connection.connect()
        except OSError as error:
            connection.close()
            raise AiError(ErrorKind.UNREACHABLE, str(error)) from error
        assert connection.sock is not None
        connection.sock.settimeout(read_seconds)
        return connection


def _wait_for_answer(connection: http.client.HTTPConnection, cancel: threading.Event | None, deadline: float) -> None:
    """Until the server starts to answer, looking at `cancel` meanwhile: a read blocked on the socket would not see it,
    and a cold model takes tens of seconds to load."""
    while not select.select([connection.sock], [], [], _CANCEL_POLL_SECONDS)[0]:
        _check_cancel(cancel)
        if time.monotonic() > deadline:
            raise TimeoutError


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ProcessCancelledError("cancelled", ("POST", "/api/chat"))


def _json(data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError as error:
        raise AiError(ErrorKind.BAD_ANSWER, f"not JSON: {data[:_ERROR_LIMIT]!r}") from error


def _error_text(data: Any, status: int) -> str:
    message = data.get("error") if isinstance(data, dict) else None
    return f"{status}: {str(message or data)[:_ERROR_LIMIT]}"
