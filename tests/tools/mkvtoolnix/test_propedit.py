from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.tools.mkvtoolnix import propedit
from showrunner.tools.mkvtoolnix.propedit import Edit, PropeditError, Property, build_arguments, edit_headers, selector
from showrunner.tools.process import ProcessTimeoutError, ProgramNotFoundError, RunResult

FILE = Path("Show Name - S01E01.mkv")
TOOL = Path("mkvpropedit.exe")


def test_the_selector_is_the_mkvmerge_id_counted_from_one() -> None:
    assert [selector(i) for i in (0, 1, 7)] == ["track:1", "track:2", "track:8"]


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        (Edit(Property.TITLE, "Show Name"), ["--edit", "info", "--set", "title=Show Name"]),
        (Edit(Property.NAME, "Name = A", 2), ["--edit", "track:3", "--set", "name=Name = A"]),
        (
            Edit(Property.LANGUAGE, "pt-BR", 1),
            ["--edit", "track:2", "--set", "language=por", "--set", "language-ietf=pt-BR"],
        ),
        (
            Edit(Property.LANGUAGE, "es-419", 1),
            ["--edit", "track:2", "--set", "language=spa", "--set", "language-ietf=es-419"],
        ),
        (
            Edit(Property.LANGUAGE, "sr-latn-rs", 1),
            ["--edit", "track:2", "--set", "language=srp", "--set", "language-ietf=sr-Latn-RS"],
        ),
        (
            Edit(Property.LANGUAGE, "cmn", 1),
            ["--edit", "track:2", "--set", "language=cmn", "--set", "language-ietf=cmn"],
        ),
        (Edit(Property.FLAG_DEFAULT, True, 0), ["--edit", "track:1", "--set", "flag-default=1"]),
        (Edit(Property.FLAG_FORCED, False, 0), ["--edit", "track:1", "--set", "flag-forced=0"]),
        (Edit(Property.FLAG_HEARING_IMPAIRED, True, 4), ["--edit", "track:5", "--set", "flag-hearing-impaired=1"]),
        (Edit(Property.FLAG_COMMENTARY, True, 4), ["--edit", "track:5", "--set", "flag-commentary=1"]),
    ],
)
def test_arguments_for_every_kind_of_edit(edit: Edit, expected: list[str]) -> None:
    assert build_arguments(FILE, [edit]) == [str(FILE), *expected]


def test_edits_of_one_track_share_a_block_and_blocks_keep_their_order() -> None:
    edits = [
        Edit(Property.NAME, "B", 2),
        Edit(Property.TITLE, "T"),
        Edit(Property.FLAG_DEFAULT, True, 2),
        Edit(Property.NAME, "A", 1),
    ]
    assert build_arguments(FILE, edits)[1:] == [
        "--edit",
        "track:3",
        "--set",
        "name=B",
        "--set",
        "flag-default=1",
        "--edit",
        "info",
        "--set",
        "title=T",
        "--edit",
        "track:2",
        "--set",
        "name=A",
    ]


@pytest.mark.parametrize(
    "make",
    [
        lambda: Edit(Property.TITLE, "T", 0),
        lambda: Edit(Property.NAME, "N"),
        lambda: Edit(Property.FLAG_DEFAULT, "1", 0),
        lambda: Edit(Property.NAME, True, 0),
        lambda: Edit(Property.LANGUAGE, "not a language", 0),
    ],
)
def test_an_edit_that_does_not_fit_its_property_is_rejected(make) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        make()


class Runner:
    def __init__(self, result: RunResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args, **_) -> RunResult:
        self.calls.append(tuple(str(a) for a in args))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def result(code: int, out: str = "", err: str = "") -> RunResult:
    return RunResult((str(TOOL),), code, out, err)


def test_all_edits_go_to_one_run(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Runner(result(0))
    monkeypatch.setattr(propedit, "run", runner)
    edit_headers(TOOL, FILE, [Edit(Property.TITLE, "T"), Edit(Property.NAME, "N", 0)], timeout=5)
    assert runner.calls == [
        (str(TOOL), str(FILE), "--edit", "info", "--set", "title=T", "--edit", "track:1", "--set", "name=N")
    ]


def test_no_edits_run_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Runner(result(0))
    monkeypatch.setattr(propedit, "run", runner)
    edit_headers(TOOL, FILE, [], timeout=5)
    assert runner.calls == []


def test_warnings_are_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(propedit, "run", Runner(result(1, "Warning: something")))
    edit_headers(TOOL, FILE, [Edit(Property.TITLE, "T")], timeout=5)


def test_an_error_gives_the_programs_own_message(monkeypatch: pytest.MonkeyPatch) -> None:
    out = "The file is being analyzed.\nError: The file 'x.mkv' could not be opened for reading: no such file.\n"
    monkeypatch.setattr(propedit, "run", Runner(result(2, out)))
    with pytest.raises(PropeditError, match=r"^Error: The file 'x.mkv' could not be opened"):
        edit_headers(TOOL, FILE, [Edit(Property.TITLE, "T")], timeout=5)


def test_an_error_without_an_error_line_gives_the_whole_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(propedit, "run", Runner(result(2, "", "Unknown option\n")))
    with pytest.raises(PropeditError, match="Unknown option"):
        edit_headers(TOOL, FILE, [Edit(Property.TITLE, "T")], timeout=5)


def test_silence_still_gives_the_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(propedit, "run", Runner(result(2)))
    with pytest.raises(PropeditError, match="exit code 2"):
        edit_headers(TOOL, FILE, [Edit(Property.TITLE, "T")], timeout=5)


@pytest.mark.parametrize("failure", [ProgramNotFoundError("no such file", ["x"]), ProcessTimeoutError("slow", ["x"])])
def test_a_program_that_cannot_run_is_a_clear_failure(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    monkeypatch.setattr(propedit, "run", Runner(failure))
    with pytest.raises(PropeditError, match=str(failure)):
        edit_headers(TOOL, FILE, [Edit(Property.TITLE, "T")], timeout=5)
