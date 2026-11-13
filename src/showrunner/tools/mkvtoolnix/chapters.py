"""Chapters as `mkvextract` writes them: Matroska chapter XML."""

from __future__ import annotations

import threading
import xml.etree.ElementTree as ET
from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import Chapter, ChapterName
from showrunner.tools.process import run

# Matroska names a chapter's language "eng" when the element is absent.
_DEFAULT_LANGUAGE = "eng"


class ChaptersError(Exception):
    """mkvextract failed or wrote something that is not chapter XML."""


def extract_chapters(
    mkvextract: Path, path: Path, *, timeout: float, cancel: threading.Event | None = None
) -> tuple[Chapter, ...]:
    result = run([mkvextract, path, "chapters"], timeout=timeout, cancel=cancel)
    if result.returncode >= 2:
        raise ChaptersError(result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}")
    return parse_chapters(result.stdout)


def parse_chapters(xml: str) -> tuple[Chapter, ...]:
    """The chapters of the first edition, nested chapters flattened in document order.

    Only the first edition is read: the app shows and edits one chapter list per file, and files with
    several editions (alternate cuts) are rare.
    """
    # mkvextract starts its output with a byte order mark, which the XML parser rejects.
    try:
        root = ET.fromstring(xml.lstrip("﻿"))
        edition = root.find("EditionEntry")
        return () if edition is None else tuple(_chapter(atom) for atom in edition.iter("ChapterAtom"))
    except (ET.ParseError, ValueError) as error:
        raise ChaptersError(f"not chapter XML: {error}") from error


def _chapter(atom: ET.Element) -> Chapter:
    names = []
    for display in atom.findall("ChapterDisplay"):
        text = display.findtext("ChapterString") or ""
        code = display.findtext("ChapLanguageIETF") or display.findtext("ChapterLanguage") or _DEFAULT_LANGUAGE
        if text:
            names.append(ChapterName(Language.parse(code), text))
    return Chapter(
        _seconds(atom.findtext("ChapterTimeStart")) or 0.0, _seconds(atom.findtext("ChapterTimeEnd")), tuple(names)
    )


def _seconds(timestamp: str | None) -> float | None:
    """`HH:MM:SS.nnnnnnnnn` to seconds."""
    if not timestamp:
        return None
    hours, minutes, seconds = timestamp.strip().split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
