from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.tools.ocr import CHUNK, OcrError, pgs, read_pgs
from showrunner.tools.process import ProcessCancelledError


class Item:
    """What pgsrip's chain asks of a subtitle image: a place in time and a height, hashable."""

    def __init__(self, index: int) -> None:
        self.index, self.start, self.end, self.height = index, index * 1000, index * 1000 + 500, 20


def items(count: int) -> list[Any]:
    return [Item(n) for n in range(count)]


class Engine:
    """Stands in for pgsrip's Tesseract engine: reads item n as "line n" (items 0, 7, 14, ... as nothing) and
    remembers the chunks it was given."""

    def __init__(self, cancel_after: threading.Event | None = None) -> None:
        self.chunks: list[int] = []
        self.cancel_after = cancel_after

    def prepare(self, languages: Any, reporter: Any = None) -> None:
        pass

    def supports(self, language: Any) -> bool:
        return True

    def recognize(self, found: list[Any], language: Any, debug_dir: Any) -> list[Any]:
        from pgsrip.engines.base import Reading

        self.chunks.append(len(found))
        if self.cancel_after is not None:
            self.cancel_after.set()
        return [Reading(f"line {item.index}" if item.index % 7 else None) for item in found]


def use(monkeypatch: pytest.MonkeyPatch, found: list[Any], engine: Engine) -> None:
    monkeypatch.setattr(pgs, "_items", lambda stream: found)
    monkeypatch.setattr(pgs, "_engine", lambda models: engine)
    monkeypatch.setattr(pgs, "installed_languages", lambda tesseract, cancel=None: frozenset({"eng"}))


def test_the_images_go_to_the_engine_in_chunks_and_unread_ones_give_no_cue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = Engine()
    use(monkeypatch, items(CHUNK + 5), engine)
    seen: list[float] = []
    cues = read_pgs(tmp_path / "a.sup", Language("eng"), Path("tesseract"), progress=seen.append)
    assert engine.chunks == [CHUNK, 5]
    assert seen == [CHUNK / (CHUNK + 5), 1.0]
    assert cues[0] == Cue(1.0, 1.5, "line 1")
    assert len(cues) == CHUNK + 5 - len([n for n in range(CHUNK + 5) if n % 7 == 0])


def test_the_program_path_is_set_for_the_read_and_restored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pytesseract

    before = pytesseract.pytesseract.tesseract_cmd
    during: list[str] = []

    class Spy(Engine):
        def recognize(self, found: list[Any], language: Any, debug_dir: Any) -> list[Any]:
            during.append(pytesseract.pytesseract.tesseract_cmd)
            return super().recognize(found, language, debug_dir)

    use(monkeypatch, items(2), Spy())
    read_pgs(tmp_path / "a.sup", None, Path("somewhere") / "tesseract")
    assert during == [str(Path("somewhere") / "tesseract")]
    assert pytesseract.pytesseract.tesseract_cmd == before


def test_cancel_stops_the_read_between_chunks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cancel = threading.Event()
    use(monkeypatch, items(CHUNK * 3), Engine(cancel_after=cancel))
    with pytest.raises(ProcessCancelledError):
        read_pgs(tmp_path / "a.sup", Language("eng"), Path("tesseract"), cancel=cancel)


def test_a_stream_without_images_and_a_language_with_no_model_are_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use(monkeypatch, [], Engine())
    with pytest.raises(OcrError, match="no subtitle image"):
        read_pgs(tmp_path / "a.sup", Language("eng"), Path("tesseract"))

    class Without(Engine):
        def supports(self, language: Any) -> bool:
            return False

    use(monkeypatch, items(3), Without())
    with pytest.raises(OcrError, match="No OCR engine"):
        read_pgs(tmp_path / "a.sup", Language("tur"), Path("tesseract"))


def test_a_tesseract_that_cannot_list_its_languages_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use(monkeypatch, items(2), Engine())
    monkeypatch.setattr(pgs, "installed_languages", lambda tesseract, cancel=None: None)
    with pytest.raises(OcrError, match="could not be asked"):
        read_pgs(tmp_path / "a.sup", Language("eng"), Path("tesseract"))


def test_the_engine_knows_only_the_models_it_was_given_and_never_downloads() -> None:
    engine = pgs._engine({"eng", "tur"})
    data = engine.tessdata
    assert data.installed_codes == {"eng", "tur"}
    assert data.download is False
    assert data.available("tur") is True
    assert data.available("deu") is False
    assert data.ensure({"eng"}) is None
