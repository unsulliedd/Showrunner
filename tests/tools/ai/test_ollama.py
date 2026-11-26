"""The Ollama adapter against a stand-in server that answers as Ollama's HTTP API does."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from showrunner.tools.ai import AiError, ChatRequest, ErrorKind, Message, OllamaBackend, Role
from showrunner.tools.process import ProcessCancelledError

type Answer = Callable[[BaseHTTPRequestHandler, dict[str, object]], None]

REQUEST = ChatRequest("sample:9b", "Translate to Turkish.", (Message(Role.USER, "Good night."),), timeout=5.0)


def lines(handler: BaseHTTPRequestHandler, chunks: list[dict[str, object]], delay: float = 0.0) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/x-ndjson")
    handler.end_headers()
    for chunk in chunks:
        handler.wfile.write(json.dumps(chunk).encode() + b"\n")
        handler.wfile.flush()
        time.sleep(delay)


def words(*parts: str, reason: str = "stop") -> list[dict[str, object]]:
    found: list[dict[str, object]] = [{"message": {"role": "assistant", "content": p}, "done": False} for p in parts]
    return [*found, {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": reason}]


class Server:
    """Answers `/api/tags` with `models` and `/api/chat` with `answer`, keeping every chat request it was sent."""

    def __init__(self) -> None:
        self.models: list[str] = ["sample:9b", "other:3b"]
        self.version = {"version": "0.40.17"}
        self.answer: Answer = lambda handler, body: lines(handler, words("İyi ", "geceler."))
        self.sent: list[dict[str, object]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                found = {
                    "/api/tags": {"models": [{"name": name} for name in outer.models]},
                    "/api/version": outer.version,
                }
                data = json.dumps(found[self.path]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.sent.append(body)
                # The client may go away, as a cancel does.
                with contextlib.suppress(OSError):
                    outer.answer(self, body)

            def log_message(self, *args: object) -> None:
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()


@pytest.fixture
def server() -> Iterator[Server]:
    found = Server()
    yield found
    found.http.shutdown()
    found.http.server_close()


def test_the_installed_models_are_listed_sorted(server: Server) -> None:
    assert OllamaBackend(server.url).models() == ["other:3b", "sample:9b"]


def test_the_server_says_its_version(server: Server) -> None:
    assert OllamaBackend(server.url).version() == "0.40.17"
    server.version = {"other": "shape"}
    with pytest.raises(AiError) as raised:
        OllamaBackend(server.url).version()
    assert raised.value.kind is ErrorKind.BAD_ANSWER


def test_a_chat_sends_the_prompt_and_messages_and_joins_the_streamed_words(server: Server) -> None:
    answer = OllamaBackend(server.url).chat(REQUEST)
    assert answer.text == "İyi geceler."
    assert answer.seconds >= 0
    sent = server.sent[0]
    assert sent["model"] == "sample:9b"
    assert sent["messages"] == [
        {"role": "system", "content": "Translate to Turkish."},
        {"role": "user", "content": "Good night."},
    ]
    # Thinking is off: a thinking model would write its reasoning before every answer.
    assert sent["think"] is False
    assert sent["stream"] is True
    # No temperature asked for: the server keeps its own.
    assert "options" not in sent


def test_a_temperature_asked_for_is_sent_as_an_option(server: Server) -> None:
    OllamaBackend(server.url).chat(dataclasses.replace(REQUEST, temperature=0.0))
    assert server.sent[0]["options"] == {"temperature": 0.0}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_a_server_that_does_not_answer_is_unreachable_and_found_fast() -> None:
    backend = OllamaBackend(f"http://127.0.0.1:{free_port()}")
    started = time.monotonic()
    for call in (backend.models, backend.version, lambda: backend.chat(REQUEST)):
        with pytest.raises(AiError) as raised:
            call()
        assert raised.value.kind is ErrorKind.UNREACHABLE
    assert time.monotonic() - started < 5


def error(status: int, text: str) -> Answer:
    def answer(handler: BaseHTTPRequestHandler, body: dict[str, object]) -> None:
        data = json.dumps({"error": text}).encode()
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    return answer


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        (error(404, "model 'sample:9b' not found"), ErrorKind.MODEL_MISSING),
        (error(500, "out of memory"), ErrorKind.BAD_ANSWER),
        (lambda h, b: lines(h, [{"error": "the runner stopped"}]), ErrorKind.BAD_ANSWER),
        # Cut off at the model's limit: the end of the answer is missing.
        (lambda h, b: lines(h, words("İyi", reason="length")), ErrorKind.BAD_ANSWER),
        (lambda h, b: lines(h, words("İyi")[:1]), ErrorKind.BAD_ANSWER),
    ],
    ids=["model-missing", "server-error", "error-line", "cut-off", "ended-early"],
)
def test_a_failed_answer_says_why(server: Server, answer: Answer, kind: ErrorKind) -> None:
    server.answer = answer
    with pytest.raises(AiError) as raised:
        OllamaBackend(server.url).chat(REQUEST)
    assert raised.value.kind is kind


def test_an_answer_slower_than_the_timeout_times_out(server: Server) -> None:
    server.answer = lambda h, b: lines(h, words("a", "b", "c", "d"), delay=0.2)
    request = ChatRequest("sample:9b", "", (), timeout=0.3)
    with pytest.raises(AiError) as raised:
        OllamaBackend(server.url).chat(request)
    assert raised.value.kind is ErrorKind.TIMEOUT


def test_a_silent_server_times_out(server: Server) -> None:
    server.answer = lambda h, b: time.sleep(2)
    with pytest.raises(AiError) as raised:
        OllamaBackend(server.url).chat(ChatRequest("sample:9b", "", (), timeout=0.3))
    assert raised.value.kind is ErrorKind.TIMEOUT


def test_cancel_ends_a_chat_waiting_for_its_first_word(server: Server) -> None:
    server.answer = lambda h, b: time.sleep(3)
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(ProcessCancelledError):
        OllamaBackend(server.url).chat(REQUEST, cancel)
    assert time.monotonic() - started < 2
