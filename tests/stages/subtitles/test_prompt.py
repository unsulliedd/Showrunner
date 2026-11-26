"""What a translation asks the model and how its answer is read: the shape is pinned, since a model's answers depend on
it and a change to it asks every window again."""

from __future__ import annotations

import pytest

from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.stages.subtitles.prompt import (
    RETRY_TEMPERATURE,
    TEMPERATURE,
    read_answer,
    retry_request,
    system_prompt,
    translate_request,
    window_text,
)
from showrunner.stages.subtitles.windows import Window
from showrunner.tools.ai import Message, Role

CUES = [
    Cue(1.0, 2.0, "Where were you?"),
    Cue(3.0, 4.0, "- At home.\n- Liar."),
    Cue(5.0, 6.0, "{\\i1}Nobody{\\i0} believes me."),
    Cue(7.0, 8.0, "I told you not\nto touch that."),
    Cue(9.0, 10.0, "Fine."),
]
# The middle three as the window, one cue of context on each side.
WINDOW = Window(1, 1, 4, 0)
ENGLISH, TURKISH = Language("eng"), Language("tur")


def test_the_system_prompt_names_both_languages_and_the_rules() -> None:
    prompt = system_prompt(ENGLISH, TURKISH)
    assert prompt.startswith("You translate the subtitles of films and TV shows from English into Turkish.")
    for rule in ("same order", "Never merge, split, skip or reorder", "line breaks", '"-"', "{\\an8}", "names"):
        assert rule in prompt
    assert "natural spoken Turkish" in prompt
    assert "context" in prompt
    # A reference of no known language names the target alone.
    assert system_prompt(None, TURKISH).startswith("You translate the subtitles of films and TV shows into Turkish.")


def test_a_window_numbers_its_own_cues_and_marks_the_context_around_them() -> None:
    assert window_text(CUES, WINDOW, 1) == "\n".join(
        [
            "Earlier lines, context only, not to translate:",
            "> Where were you?",
            "",
            "Translate these cues:",
            "[1]",
            "- At home.",
            "- Liar.",
            "[2]",
            "{\\i1}Nobody{\\i0} believes me.",
            "[3]",
            "I told you not",
            "to touch that.",
            "",
            "Later lines, context only, not to translate:",
            "> Fine.",
        ]
    )
    # The first window has nothing before it, the last nothing after it.
    first = window_text(CUES, Window(0, 0, 5, 0), 2)
    assert first.startswith("Translate these cues:\n[1]\nWhere were you?")
    assert "Later lines" not in first


def test_the_request_asks_for_a_fixed_temperature_and_its_retry_for_a_little_more() -> None:
    request = translate_request(CUES, WINDOW, model="sample:9b", source=ENGLISH, target=TURKISH, context=1)
    assert (request.model, request.temperature) == ("sample:9b", TEMPERATURE)
    assert request.temperature == 0
    assert [m.role for m in request.messages] == [Role.USER]
    again = retry_request(WINDOW, request, "[1]\nEvde.")
    assert again.temperature == RETRY_TEMPERATURE
    assert again.messages[:2] == (*request.messages, Message(Role.ASSISTANT, "[1]\nEvde."))
    assert "[1] to [3]" in again.messages[2].content
    # A server answer with no text adds no empty turn of the model's.
    assert [m.role for m in retry_request(WINDOW, request, "").messages] == [Role.USER, Role.USER]


def test_an_answer_takes_the_window_s_timing_and_keeps_its_lines_and_markup() -> None:
    answer = (
        "```\n[1]\n- Evdeydim.\n- Yalan!.\n\n[2] {\\i1}Kimse{\\i0} bana dinlemiyor.\n[3]\nSana ona\ndokunma dedim.\n```"
    )
    cues = read_answer(CUES, WINDOW, answer)
    assert [cue.text for cue in cues] == [
        "- Evdeydim.\n- Yalan!.",
        "{\\i1}Kimse{\\i0} bana dinlemiyor.",
        "Sana ona\ndokunma dedim.",
    ]
    assert [(cue.start, cue.end) for cue in cues] == [(3.0, 4.0), (5.0, 6.0), (7.0, 8.0)]


@pytest.mark.parametrize(
    "answer",
    [
        "[1]\nEvde.\n[2]\nKimse.",  # one cue short
        "[1]\nEvde.\n[3]\nDokunma.\n[2]\nKimse.",  # out of order
        "[1]\nEvde.\n[2]\nKimse.\n[2]\nKimse.\n[3]\nDokunma.",  # one cue twice
        "Evde. Kimse. Dokunma.",  # no numbers at all
    ],
)
def test_an_answer_without_each_number_once_and_in_order_cannot_be_read(answer: str) -> None:
    with pytest.raises(ValueError, match="cue"):
        read_answer(CUES, WINDOW, answer)


def test_a_cue_the_answer_leaves_empty_keeps_its_own_text() -> None:
    cues = read_answer(CUES, WINDOW, "[1]\nEvde.\n[2]\n\n[3]\nDokunma.")
    assert [cue.text for cue in cues] == ["Evde.", CUES[2].text, "Dokunma."]
