"""Tesseract's language data: which models are installed, and the model a language is read with."""

from __future__ import annotations

import threading
from pathlib import Path

from showrunner.core.language import Language
from showrunner.tools.process import ProcessError, run

# The model Tesseract reads with when a track names no language.
DEFAULT_CODE = "eng"
_SCRIPT_CODES = {
    ("aze", "Cyrl"): "aze_cyrl",
    ("srp", "Latn"): "srp_latn",
    ("uzb", "Cyrl"): "uzb_cyrl",
    ("zho", "Hans"): "chi_sim",
    ("zho", "Hant"): "chi_tra",
}
_TRADITIONAL_REGIONS = frozenset({"HK", "MO", "TW"})
# Tesseract's own sub-model that detects the orientation of a page: it reads no language.
_NOT_LANGUAGES = frozenset({"osd"})
_LIST_TIMEOUT = 30.0


def tesseract_code(language: Language | None) -> str:
    """The name of the model that reads `language`: its three-letter code, except where Tesseract names a model for
    one script (Chinese is `chi_sim` or `chi_tra`, Serbian in Latin letters `srp_latn`)."""
    if language is None:
        return DEFAULT_CODE
    script = language.script
    if language.alpha3 == "zho" and script is None:
        script = "Hant" if language.region in _TRADITIONAL_REGIONS else "Hans"
    return _SCRIPT_CODES.get((language.alpha3, script or ""), language.alpha3)


def model_stamp(tesseract: Path, language: Language | None) -> str:
    """What the model `language` is read with is now, in the data folder beside the program: its name, size and
    modification time, so another model installed in its place gives another stamp. Empty when it is not there."""
    code = tesseract_code(language)
    try:
        info = (tesseract.parent / "tessdata" / f"{code}.traineddata").stat()
    except OSError:
        return ""
    return f"{code}:{info.st_size}:{info.st_mtime_ns}"


def installed_languages(tesseract: Path, *, cancel: threading.Event | None = None) -> frozenset[str] | None:
    """The models Tesseract finds, or None when it cannot be asked (the program is broken or gone)."""
    try:
        result = run([tesseract, "--list-langs"], timeout=_LIST_TIMEOUT, cancel=cancel)
    except ProcessError:
        return None
    if result.returncode != 0:
        return None
    # The first line names the data folder ("List of available languages in ...").
    lines = (line.strip() for line in result.output.splitlines())
    return frozenset(line for line in lines if line and not line.startswith("List of") and line not in _NOT_LANGUAGES)
