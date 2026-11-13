"""Subtitle files: language and flags from the name, else the language from the text."""

from __future__ import annotations

import re
from pathlib import Path

from showrunner.core.encoding import decode_text
from showrunner.core.language import Language
from showrunner.core.media import SubtitleFile
from showrunner.stages.scan.extensions import TEXT_SUBTITLE_EXTENSIONS
from showrunner.stages.scan.names import parse_subtitle_name

_TIMING_LINE = re.compile(r"^\s*\d+\s*$|^[\d:,.]+\s*-->.*$", re.MULTILINE)
_MARKUP = re.compile(r"<[^>]+>|\{[^}]*\}")
# Enough text for a reliable guess; the rest of a long file adds time only.
_SAMPLE_CHARS = 20_000


def _spoken_text(text: str, suffix: str) -> str:
    if suffix in (".ass", ".ssa"):
        # The text is the tenth field of a dialogue line and may itself contain commas.
        text = "\n".join(line.split(",", 9)[-1] for line in text.splitlines() if line.startswith("Dialogue:"))
    return _MARKUP.sub(" ", _TIMING_LINE.sub(" ", text))


def detect_language(path: Path) -> Language | None:
    """Guess the language of a text subtitle from what is said in it; None when unreadable or unsure."""
    from langdetect import DetectorFactory, detect
    from langdetect.lang_detect_exception import LangDetectException

    try:
        text = _spoken_text(decode_text(path.read_bytes()), path.suffix.lower())
    except OSError:
        return None
    # The detector is random unless seeded; a scan must give the same answer every time.
    DetectorFactory.seed = 0
    try:
        code = detect(text[:_SAMPLE_CHARS])
    except LangDetectException:
        return None
    return Language.parse(code) or Language.parse(code.split("-")[0])


def read_subtitle(path: Path, *, detect: bool = True) -> SubtitleFile:
    """The file with the language and flags its name gives, the language otherwise guessed from the text."""
    name = parse_subtitle_name(path.name)
    language = name.language
    if language is None and detect and path.suffix.lower() in TEXT_SUBTITLE_EXTENSIONS:
        language = detect_language(path)
    return SubtitleFile(path, language, name.forced, name.sdh)
