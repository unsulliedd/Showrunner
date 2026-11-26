"""The model choice: Settings' AI models section, the Subtitles tab's Translate with row, and the words Review and the
row use when AI work cannot run."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from showrunner.app.ai import AI, AiStatus
from showrunner.app.dependencies.service import mkvpropedit_from, programs_from
from showrunner.app.jobs.stages import Stage, pipeline
from showrunner.stages.subtitles import AiModels, StepKind, SubtitlePlan, Wanted
from showrunner.tools.ai import AiError, ChatAnswer, ChatRequest, ErrorKind
from showrunner.ui.quick.review import ai_model, unavailable_text
from showrunner.ui.quick.subtitles import unavailable
from showrunner.ui.quick.window import WindowController
from showrunner.ui.quick.workspace import Statuses

from .conftest import ENGINES, never, program_statuses
from .test_choices import open_season, settle

RUNNING = AiStatus("ollama", True, ("other:3b", "sample:9b"))


class Server:
    """Answers every check, the window's own background ones included, as `status` says."""

    name = "ollama"

    def __init__(self, status: AiStatus) -> None:
        self.status = status

    def models(self) -> tuple[str, ...]:
        if not self.status.running:
            raise AiError(ErrorKind.UNREACHABLE, "refused")
        return self.status.models

    def version(self) -> str:
        self.models()
        return "0.40.17"

    def chat(self, request: ChatRequest, cancel: object = None) -> ChatAnswer:
        raise NotImplementedError


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Callable[[AiStatus], None]:
    """Makes the AI server answer as given, and checks it once, as the window's background check would."""

    def answer(status: AiStatus) -> None:
        monkeypatch.setattr(AI, "backend", Server(status))
        AI.check()

    return answer


def model_row(controller: WindowController) -> dict[str, Any]:
    return next(r for r in controller.subtitles["rows"] if r["key"] == "model")


def test_the_words_name_the_server_and_the_model() -> None:
    assert unavailable("ai") == "Ollama is not running"
    assert unavailable("model", "gone:7b") == "The model gone:7b is not installed"
    assert unavailable("no_model") == "No AI model is chosen in Settings"
    assert unavailable_text("ai", 3).startswith("Ollama is not running, so 3 subtitles are left out.")
    assert unavailable_text("model", 1, "gone:7b").startswith("The model gone:7b is not installed, so 1 subtitle")


def test_the_settings_section_lists_the_installed_models_and_keeps_the_choice(
    controller: WindowController, server: Callable[[AiStatus], None]
) -> None:
    settings = controller.settings
    assert settings.ai["state"] == "Asking Ollama…"
    server(AiStatus("ollama", False))
    assert settings.ai["state"].startswith("Ollama is not running.")
    server(RUNNING)
    shown = settings.ai
    assert (shown["state"], shown["model"]) == ("Ollama is running, with 2 models installed", "No model chosen")
    assert [m["key"] for m in shown["models"]] == ["other:3b", "sample:9b"]
    settings.set_ai_model("sample:9b")
    assert settings.ai["model"] == "sample:9b"
    server(AiStatus("ollama", True, ("other:3b",)))
    assert settings.ai["model"] == "sample:9b · not installed"


def test_the_row_follows_settings_until_the_place_picks_an_installed_model(
    controller: WindowController, library: Any, qtbot: QtBot, server: Callable[[AiStatus], None]
) -> None:
    server(RUNNING)
    open_season(controller, library, qtbot)
    row = model_row(controller)
    assert row["text"] == "From Settings, where no model is chosen yet"
    assert [(p["key"], p["text"]) for p in row["pick"]] == [
        ("", "The model chosen in Settings"),
        ("other:3b", "other:3b"),
        ("sample:9b", "sample:9b"),
    ]
    controller.settings.set_ai_model("sample:9b")
    settle(controller, qtbot)
    assert model_row(controller)["text"] == "From Settings: sample:9b (Ollama)"

    controller.pick_model("other:3b")
    settle(controller, qtbot)
    row = model_row(controller)
    assert (row["text"], row["own"]) == ("other:3b", True)
    server(AiStatus("ollama", True, ("sample:9b",)))
    controller.subtitle_settings.refresh()
    assert model_row(controller)["text"] == "other:3b · not installed"
    controller.pick_model("")
    settle(controller, qtbot)
    assert model_row(controller)["text"] == "From Settings: sample:9b (Ollama)"


def with_ai(ai: AiModels | None) -> Callable[[Statuses], Sequence[Stage]]:
    """Every engine, the server answering only where `ai` is given, as the real pipeline has it."""
    kinds = [kind for kind in ENGINES if ai is not None or kind is not StepKind.AI]
    return lambda statuses: pipeline(
        programs_from(statuses), mkvpropedit_from(statuses), runners=dict.fromkeys(kinds, never), ai=ai
    )


@pytest.fixture
def make_window(qapp: QApplication) -> Iterator[Callable[[AiModels | None], WindowController]]:
    made: list[WindowController] = []

    def make(ai: AiModels | None) -> WindowController:
        made.append(WindowController(statuses=program_statuses, make_pipeline=with_ai(ai)))
        return made[-1]

    yield make
    for controller in made:
        controller.deleteLater()


@pytest.mark.parametrize(
    ("ai", "said"),
    [
        (None, "Ollama is not running, so 10 subtitles are left out."),
        (AiModels("gone:7b", ("sample:9b",)), "The model gone:7b is not installed, so 10 subtitles are left out."),
        (AiModels("", ("sample:9b",)), "No AI model is chosen in Settings, so 10 subtitles are left out."),
    ],
    ids=["no-server", "not-installed", "none-chosen"],
)
def test_review_and_the_row_say_why_a_translation_is_left_out(
    make_window: Callable[[AiModels | None], WindowController],
    library: Any,
    qtbot: QtBot,
    ai: AiModels | None,
    said: str,
) -> None:
    controller = make_window(ai)
    open_season(controller, library, qtbot)
    workspace = controller.workspace
    assert workspace.key is not None
    options = workspace.batches.profile(workspace.key).for_stage("subtitles")
    workspace.set_options("subtitles", replace(options, languages={"de": Wanted.WANTED}))
    settle(controller, qtbot)
    problems = [line for group in controller.review["groups"] for line in group["problems"]]
    assert any(line.startswith(said) for line in problems), problems
    assert model_row(controller)["note"] == said.split(",")[0]


def test_the_plans_follow_the_server_and_the_settings_model(
    controller: WindowController,
    library: Any,
    qtbot: QtBot,
    server: Callable[[AiStatus], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through the window's own pipeline: a new answer from the server or a new Settings model plans the place again."""

    def missing() -> set[tuple[tuple[StepKind, ...], str]]:
        found = set()
        for file in controller.workspace.current_files():
            stage = file.plan_for("subtitles")
            assert stage is not None
            assert isinstance(stage.plan, SubtitlePlan)
            found |= {(f.missing, ai_model(f)) for f in stage.plan.left_out}
        return found

    server(AiStatus("ollama", False))
    open_season(controller, library, qtbot)
    workspace = controller.workspace
    assert workspace.key is not None
    options = workspace.batches.profile(workspace.key).for_stage("subtitles")
    workspace.set_options("subtitles", replace(options, languages={"de": Wanted.WANTED}))
    settle(controller, qtbot)
    assert missing() == {((StepKind.AI,), "")}
    # The server starts: the window's background check sees it and plans again.
    monkeypatch.setattr(AI, "backend", Server(RUNNING))
    controller.found.check_ai(now=True)
    qtbot.waitUntil(lambda: missing() == {((StepKind.MODEL,), "")})
    controller.settings.set_ai_model("sample:9b")
    settle(controller, qtbot)
    # Nothing is missing once the model is chosen: the translation is planned.
    assert missing() == set()
