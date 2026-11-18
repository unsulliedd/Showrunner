from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.tools.mkvtoolnix import languages as listing
from showrunner.tools.mkvtoolnix.languages import ListLanguagesError, MkvLanguage, list_languages, parse_languages
from showrunner.tools.process import RunResult

TABLE = """\
English language name                                      | ISO 639-3 code | ISO 639-2 code | ISO 639-1 code
-----------------------------------------------------------+----------------+----------------+---------------
Aasáx                                                      | aas            |                |
Dutch                                                      | dut            | dut            | nl
Romance languages                                          | roa            | roa            |
"""


def result(returncode: int, stdout: str = "", stderr: str = "") -> RunResult:
    return RunResult(("mkvmerge",), returncode, stdout, stderr)


def test_the_rows_of_the_table_are_read_with_their_codes() -> None:
    rows = parse_languages(TABLE)
    assert [r.name for r in rows] == ["Aasáx", "Dutch", "Romance languages"]
    assert rows[1] == MkvLanguage("Dutch", "dut", "dut", "nl")
    assert rows[1].codes == ("dut", "nl")
    assert rows[0].codes == ("aas",)


def test_a_line_that_is_not_a_row_is_skipped() -> None:
    assert parse_languages(TABLE + "\nnot a row\n | | | \n") == parse_languages(TABLE)


def test_the_list_comes_from_one_run_of_mkvmerge(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[object]] = []

    def run(args: list[object], **_: object) -> RunResult:
        seen.append(args)
        return result(0, TABLE)

    monkeypatch.setattr(listing, "run", run)
    assert len(list_languages(Path("mkvmerge.exe"), timeout=5)) == 3
    assert seen == [[Path("mkvmerge.exe"), "--ui-language", "en", "--list-languages"]]


@pytest.mark.parametrize("answer", [result(2, "", "Error: nope"), result(0, ""), result(0, "garbage")])
def test_no_list_is_an_error(monkeypatch: pytest.MonkeyPatch, answer: RunResult) -> None:
    monkeypatch.setattr(listing, "run", lambda *_, **__: answer)
    with pytest.raises(ListLanguagesError):
        list_languages(Path("mkvmerge.exe"), timeout=5)
