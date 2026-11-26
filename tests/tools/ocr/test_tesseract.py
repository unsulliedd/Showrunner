from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from showrunner.core.language import Language
from showrunner.tools.ocr import installed_languages, model_stamp, tesseract
from showrunner.tools.process import ProgramNotFoundError, RunResult

LISTING = 'List of available languages in "C:\\Tesseract-OCR/tessdata/" (3):\neng\nosd\ntur\n'


def test_a_language_is_read_with_the_model_of_its_code_or_script() -> None:
    assert tesseract.tesseract_code(None) == "eng"
    assert tesseract.tesseract_code(Language("tur")) == "tur"
    assert tesseract.tesseract_code(Language("zho")) == "chi_sim"
    assert tesseract.tesseract_code(Language("zho", "TW")) == "chi_tra"
    assert tesseract.tesseract_code(Language("zho", script="Hant")) == "chi_tra"
    assert tesseract.tesseract_code(Language("srp", script="Latn")) == "srp_latn"


def test_the_model_stamp_is_the_model_files_name_size_and_time(tmp_path: Path) -> None:
    program = tmp_path / "tesseract.exe"
    assert model_stamp(program, Language("eng")) == ""
    (tmp_path / "tessdata").mkdir()
    model = tmp_path / "tessdata" / "chi_sim.traineddata"
    model.write_bytes(b"1234")
    stamp = model_stamp(program, Language("zho"))
    assert stamp == f"chi_sim:4:{model.stat().st_mtime_ns}"
    assert model_stamp(program, None) == ""


def fake_run(result: RunResult | Exception) -> Any:
    def run(args: Any, **_: Any) -> RunResult:
        if isinstance(result, Exception):
            raise result
        return result

    return run


def test_the_installed_models_are_the_listed_ones_without_the_orientation_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tesseract, "run", fake_run(RunResult(("tesseract",), 0, LISTING, "")))
    assert installed_languages(Path("tesseract")) == {"eng", "tur"}


def test_a_program_that_cannot_be_asked_gives_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tesseract, "run", fake_run(ProgramNotFoundError("gone", [])))
    assert installed_languages(Path("tesseract")) is None
    monkeypatch.setattr(tesseract, "run", fake_run(RunResult(("tesseract",), 1, "", "broken")))
    assert installed_languages(Path("tesseract")) is None
