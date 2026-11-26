"""What the AI server last said about itself, and what the plans make of it."""

from __future__ import annotations

import threading

import pytest

from showrunner.app import ai as watch_module
from showrunner.app.ai import AiStatus, AiWatch, ai_models
from showrunner.app.jobs.stages import SubtitlesStage
from showrunner.stages.subtitles import AiModels, StepKind
from showrunner.tools.ai import AiError, ChatAnswer, ChatRequest, ErrorKind


class Server:
    name = "ollama"

    def __init__(self) -> None:
        self.up = True
        self.installed = ["sample:9b"]

    def models(self) -> list[str]:
        if not self.up:
            raise AiError(ErrorKind.UNREACHABLE, "refused")
        return self.installed

    def version(self) -> str:
        return "0.40.17"

    def chat(self, request: ChatRequest, cancel: threading.Event | None = None) -> ChatAnswer:
        raise NotImplementedError


def test_the_last_answer_is_kept_until_a_check_replaces_it(monkeypatch: pytest.MonkeyPatch) -> None:
    server = Server()
    watch = AiWatch(server)
    assert (watch.status(), watch.stale()) == (None, True)
    assert watch.check() == AiStatus("ollama", True, ("sample:9b",))
    assert not watch.stale()
    server.up = False
    # An old answer stays in use, so a reviewed plan does not change under the user.
    monkeypatch.setattr(watch_module.watch, "FRESH_SECONDS", -1.0)  # the answer has grown old
    assert watch.stale()
    assert watch.status() == AiStatus("ollama", True, ("sample:9b",))
    stopped = watch.check()
    assert (stopped.running, stopped.models) == (False, ())
    assert "refused" in stopped.detail


def test_the_plans_get_the_models_only_while_the_server_answers() -> None:
    assert ai_models(None, "sample:9b") is None
    assert ai_models(AiStatus("ollama", False), "sample:9b") is None
    assert ai_models(AiStatus("ollama", True, ("sample:9b",)), "sample:9b") == AiModels("sample:9b", ("sample:9b",))


def test_ai_work_is_available_to_the_stage_only_while_a_server_answers() -> None:
    assert StepKind.AI not in SubtitlesStage().available
    assert StepKind.AI in SubtitlesStage(ai=AiModels()).available
