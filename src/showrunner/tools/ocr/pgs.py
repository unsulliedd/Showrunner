"""Reading a PGS (picture) subtitle stream as text with pgsrip's decoder and its Tesseract engine.

pgsrip is imported inside the functions, since loading it brings OpenCV and takes a moment. It starts no program of its
own here: the stream comes in as a file the caller extracted (with mkvextract through its adapter), and the models
Tesseract has are asked through `installed_languages`, not through pytesseract, whose own question shows a console
window. What is left is Tesseract reading the images, which pgsrip starts through pytesseract: with a hidden window, but
without a timeout and with no way to stop a started process. Cancel therefore acts between chunks of the stream, which
is how progress is reported as well. Model downloads are switched off, since the user chooses what to install.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from showrunner.core.cue import Cue
from showrunner.core.language import Language
from showrunner.tools.ocr.tesseract import installed_languages
from showrunner.tools.process import ProcessCancelledError

if TYPE_CHECKING:
    from pgsrip.formats.pgs import Item, PaletteEntry

# How many subtitle images go to Tesseract at once: a chunk is the unit of Cancel and of progress, and pgsrip packs the
# images of a chunk into a few large pictures, so a larger chunk is a little faster.
CHUNK = 120
# Names the way the pictures are prepared and read; it changes with that way, so text read before is read again.
READING = "shown-palette"
# Tesseract is given a path through one process-wide setting, so two reads never overlap.
_LOCK = threading.Lock()


class OcrError(Exception):
    """The stream could not be read as text; the message says why."""


def read_pgs(
    stream: Path,
    language: Language | None,
    tesseract: Path,
    *,
    progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> list[Cue]:
    """The lines of the PGS stream `stream` (a `.sup` file), read as `language` by the Tesseract at `tesseract`. A
    picture Tesseract could not read gives no cue. Raises `OcrError`; Cancel ends it with `ProcessCancelledError`."""
    from pgsrip.errors import PgsripError

    try:
        items = _items(stream)
        if not items:
            raise OcrError(f"{stream.name}: no subtitle image in the stream")
        with _LOCK:
            return _read(items, language, tesseract, progress, cancel)
    except PgsripError as error:
        raise OcrError(str(error)) from error


def _items(stream: Path) -> list[Item]:
    from pgsrip.formats.pgs import read_display_sets, read_items

    name = stream.name
    items = read_items(read_display_sets(stream.read_bytes(), name), name)
    for item in items:
        item.image = item.image._replace(palette=shown(item.image.palette))
    return items


def shown(palette: Sequence[PaletteEntry]) -> list[PaletteEntry]:
    """The palette with each colour's brightness as it shows over a dark picture. pgsrip takes every bright entry for
    ink whatever its transparency, and some discs give the transparent background a bright colour: their letters would
    reach Tesseract as hollow outlines in a black field."""
    return [entry._replace(y=entry.y * entry.alpha // 255) for entry in palette]


def _read(
    items: Sequence[Item],
    language: Language | None,
    tesseract: Path,
    progress: Callable[[float], None] | None,
    cancel: threading.Event | None,
) -> list[Cue]:
    import pytesseract
    from pgsrip.engines.chain import read_cues

    models = installed_languages(tesseract, cancel=cancel)
    if models is None:
        raise OcrError(f"{tesseract.name} could not be asked for its languages")
    engine = _Chunked(_engine(models), cancel, progress)
    previous = pytesseract.pytesseract.tesseract_cmd
    pytesseract.pytesseract.tesseract_cmd = str(tesseract)
    try:
        cues, _seconds = read_cues(list(items), _babelfish(language), [engine])
    finally:
        pytesseract.pytesseract.tesseract_cmd = previous
    return [Cue(cue.start / 1000, cue.end / 1000, cue.text) for cue in cues if cue.text]


def _engine(models: Iterable[str]) -> Any:
    """pgsrip's Tesseract engine over the models given, which it neither asks Tesseract for nor downloads."""
    from pgsrip.engines.tessdata import Tessdata
    from pgsrip.engines.tesseract import TesseractEngine

    class Installed(Tessdata):
        def __init__(self) -> None:
            super().__init__(download=False)

        @property
        def installed_codes(self) -> set[str]:
            return set(models)

    return TesseractEngine(tessdata=Installed())


def _babelfish(language: Language | None) -> Any:
    """pgsrip's own language type, which it takes the model name from."""
    from babelfish import Language as Babelfish

    if language is None:
        return Babelfish("und")
    region = language.region if language.region and len(language.region) == 2 and language.region.isalpha() else None
    try:
        return Babelfish(language.alpha3, region, language.script)
    except ValueError:
        return Babelfish(language.alpha3)


class _Chunked:
    """An OCR engine that reads the images in chunks of `CHUNK`, so Cancel and progress act between chunks."""

    def __init__(self, inner: Any, cancel: threading.Event | None, progress: Callable[[float], None] | None) -> None:
        self._inner = inner
        self._cancel = cancel
        self._progress = progress

    def prepare(self, languages: Iterable[Any], reporter: Callable[[str], None] | None = None) -> None:
        self._inner.prepare(languages, reporter)

    def supports(self, language: Any) -> bool:
        return bool(self._inner.supports(language))

    def engine_for(self, language: Any) -> _Chunked | None:
        return self if self.supports(language) else None

    def recognize(self, items: list[Item], language: Any, debug_dir: str | None) -> list[Any]:
        readings: list[Any] = []
        for start in range(0, len(items), CHUNK):
            if self._cancel is not None and self._cancel.is_set():
                raise ProcessCancelledError("cancelled", ())
            readings += self._inner.recognize(items[start : start + CHUNK], language, debug_dir)
            if self._progress is not None:
                self._progress(len(readings) / len(items))
        return readings
