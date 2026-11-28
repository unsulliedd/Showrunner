# ruff: noqa: RUF001 (Turkish letters are the point of this data)
"""The re-split step: by timing, or with AI where each window's answer must keep every word in order, a window that
does not going by timing, and a server that goes away sending the rest by timing."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.stages.subtitles import Lines, Step, StepKind
from showrunner.stages.subtitles.resplit import plain_words
from showrunner.stages.subtitles.resplit_ai import ResplitReport, read_report, read_split, resplit_runner
from showrunner.stages.subtitles.windows import Window
from showrunner.stages.subtitles.work import StepWork
from showrunner.tools.ai import AiError, ErrorKind
from showrunner.tools.process import ProcessCancelledError

ENGLISH, TURKISH = Language("eng"), Language("tur")


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    """Six reference cues of two seconds, and three Turkish lines each said over two of them."""
    reference, subtitle = tmp_path / "reference.srt", tmp_path / "synced.tr.srt"
    write_cues(reference, [Cue(2.0 * n, 2.0 * n + 2, f"English {n}") for n in range(6)])
    lines = [Cue(4.0 * n, 4.0 * n + 4, f"bir{n} iki{n} üç{n} dört{n}") for n in range(3)]
    write_cues(subtitle, lines)
    return reference, subtitle


def work(files: tuple[Path, Path], tmp_path: Path, way: Lines = Lines.WITH_AI, size: int = 2) -> StepWork:
    step = Step(StepKind.RESPLIT, settings=(("window", str(size)),), model="sample:9b", way=way)
    if way is Lines.BY_TIMING:
        step = Step(StepKind.RESPLIT, way=way)
    output = tmp_path / "out" / "tr.srt"
    output.parent.mkdir(exist_ok=True)
    return StepWork(step, tmp_path / "v.mkv", files[1], files[0], TURKISH, None, output, ENGLISH)


def texts(path: Path) -> list[str]:
    return [cue.text for cue in read_cues(path, TURKISH)]


def test_by_timing_needs_no_model_and_splits_each_line_over_its_cues(files: tuple[Path, Path], tmp_path: Path) -> None:
    given = work(files, tmp_path, Lines.BY_TIMING)

    def no_backend() -> Any:
        raise AssertionError("by timing asks no model")

    resplit_runner(no_backend)(given, None)
    assert texts(given.output) == [f"{a}{n} {b}{n}" for n in range(3) for a, b in (("bir", "iki"), ("üç", "dört"))]
    assert [cue.start for cue in read_cues(given.output, TURKISH)] == [2.0 * n for n in range(6)]
    assert read_report(given.output) is None


def test_with_ai_the_model_s_cuts_are_used_and_the_report_says_so(
    files: tuple[Path, Path], tmp_path: Path, splitter: Any
) -> None:
    backend = splitter()
    given = work(files, tmp_path)
    resplit_runner(lambda: backend)(given, None)
    assert texts(given.output) == [f"bir{n}" if i == 0 else f"iki{n} üç{n} dört{n}" for n in range(3) for i in (0, 1)]
    assert read_report(given.output) == ResplitReport("sample:9b", 3, 3)
    # The model sees each English cue with the Turkish words the timing gave it, at temperature 0.
    assert backend.asked[0].messages[0].content == (
        "[1]\nEnglish: English 0\nTurkish: bir0 iki0\n[2]\nEnglish: English 1\nTurkish: üç0 dört0"
    )
    assert {request.temperature for request in backend.asked} == {0.0}


def test_a_window_whose_answer_changes_a_word_goes_by_timing(
    files: tuple[Path, Path], tmp_path: Path, splitter: Any
) -> None:
    def changes_window_two(count: int, words: list[str]) -> str:
        return splitter.last_cue(count, ["bir9" if word == "bir1" else word for word in words])

    backend = splitter(changes_window_two)
    given = work(files, tmp_path)
    resplit_runner(lambda: backend)(given, None)
    # Asked again once, then by timing; the others as the model said.
    assert texts(given.output)[2:4] == ["bir1 iki1", "üç1 dört1"]
    assert texts(given.output)[0] == "bir0"
    assert read_report(given.output) == ResplitReport("sample:9b", 3, 3, by_timing=(2,), retried=1)
    assert len(backend.asked) == 4


def test_a_server_gone_sends_the_rest_by_timing_and_still_writes(
    files: tuple[Path, Path], tmp_path: Path, splitter: Any
) -> None:
    backend = splitter(fail=lambda asked: AiError(ErrorKind.UNREACHABLE) if asked >= 2 else None)
    given = work(files, tmp_path)
    resplit_runner(lambda: backend)(given, None)
    assert texts(given.output)[:2] == ["bir0", "iki0 üç0 dört0"]
    assert texts(given.output)[2:] == ["bir1 iki1", "üç1 dört1", "bir2 iki2", "üç2 dört2"]
    assert read_report(given.output) == ResplitReport("sample:9b", 3, 3, by_timing=(2, 3))
    # Asked once more only: the server is not asked again for each window left.
    assert len(backend.asked) == 2


def test_a_rerun_reuses_the_answered_windows(files: tuple[Path, Path], tmp_path: Path, splitter: Any) -> None:
    given = work(files, tmp_path)
    resplit_runner(lambda: splitter())(given, None)
    again = splitter()
    resplit_runner(lambda: again)(given, None)
    assert again.asked == []
    assert read_report(given.output) == ResplitReport("sample:9b", 3, 3, reused=3)


def test_a_cancel_ends_the_step(files: tuple[Path, Path], tmp_path: Path, splitter: Any) -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ProcessCancelledError):
        resplit_runner(lambda: splitter())(work(files, tmp_path), cancel)


def test_a_label_echoed_before_a_cue_s_words_is_not_a_word() -> None:
    own = [Cue(0.0, 1.0, "Merhaba"), Cue(1.0, 2.0, "dostum")]
    answer = "[1]\nTurkish: Merhaba dostum\n[2]\nTurkish:"
    assert [cue.text for cue in read_split(own, Window(0, 0, 2, 0), answer, frozenset())] == ["Merhaba dostum", ""]


def test_an_answer_may_leave_a_cue_empty_and_keeps_the_markup() -> None:
    own = [Cue(0.0, 1.0, r"{\i1}Merhaba"), Cue(1.0, 2.0, r"dostum{\i0}")]
    answered = read_split(own, Window(0, 0, 2, 0), "[1]\nMerhaba dostum\n[2]\n", frozenset())
    assert [cue.text for cue in answered] == [r"{\i1}Merhaba dostum{\i0}", ""]


@pytest.mark.parametrize(
    "answer",
    [
        "[1]\nMerhaba\n[2]\ndostum nasılsın",  # a word added
        "[1]\nMerhaba\n[2]\n",  # a word dropped
        "[1]\ndostum\n[2]\nMerhaba",  # reordered
        "[1]\nmerhaba\n[2]\ndostum",  # a letter's case changed
        "[2]\nMerhaba\n[1]\ndostum",  # numbers out of order
    ],
)
def test_an_answer_that_does_not_keep_every_word_in_order_cannot_be_read(answer: str) -> None:
    own = [Cue(0.0, 1.0, "Merhaba"), Cue(1.0, 2.0, "dostum")]
    with pytest.raises(ValueError, match=r"cues|words"):
        read_split(own, Window(0, 0, 2, 0), answer, frozenset())


def test_letters_composed_another_way_are_the_same_word() -> None:
    own = [Cue(0.0, 1.0, "İyi"), Cue(1.0, 2.0, "günler")]
    decomposed = "I\u0307yi"  # I and a combining dot above
    assert [c.text for c in read_split(own, Window(0, 0, 2, 0), f"[1]\n{decomposed} günler\n[2]\n", frozenset())] == [
        "İyi günler",
        "",
    ]


def test_no_word_moves_across_a_line_kept_with_its_own_timing() -> None:
    own = [Cue(0.0, 1.0, "bir"), Cue(5.0, 6.0, "iki")]
    with pytest.raises(ValueError, match="moved across"):
        read_split(own, Window(0, 0, 2, 0), "[1]\nbir iki\n[2]\n", frozenset({1}))
    assert plain_words(read_split(own, Window(0, 0, 2, 0), "[1]\nbir\n[2]\niki", frozenset({1}))[1].text) == ["iki"]
