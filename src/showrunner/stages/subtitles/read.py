"""The engines that read a subtitle out of the video: a text track taken out with mkvextract, a picture (PGS) track read
as text by OCR."""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from showrunner.core.cue import FORMATS, Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.track import Track
from showrunner.stages.subtitles.clean import fix_ocr
from showrunner.stages.subtitles.plan import track_format
from showrunner.stages.subtitles.work import Runner, StepWork
from showrunner.tools.cleanit import RuleBook
from showrunner.tools.mkvtoolnix.extract import extract_track
from showrunner.tools.ocr import read_pgs

# The share of an OCR step that taking the stream out of the video is.
_EXTRACT_SHARE = 0.1


def read_runner(mkvextract: Path) -> Runner:
    """The runner of the read step: the track of the work taken out of the video as the result. A result in the format
    the track has outside the video is the extracted file itself, styles included; for another format (the reference
    is SubRip whatever the track is) the cues are written again."""

    def run(work: StepWork, cancel: threading.Event | None) -> None:
        track = _track(work)
        with _folder(work.output) as scratch:
            extracted = Path(scratch) / f"track.{track_format(track)}"
            extract_track(mkvextract, work.video, track.id, extracted, progress=work.progress, cancel=cancel)
            if FORMATS[extracted.suffix] == FORMATS[work.output.suffix]:
                os.replace(extracted, work.output)
            else:
                write_cues(work.output, read_cues(extracted, work.language), language=work.language)

    return run


def ocr_runner(mkvextract: Path, tesseract: Path, book: Callable[[], RuleBook]) -> Runner:
    """The runner of the OCR step: the picture track of the work read as text, with the OCR fixes, which a picture
    subtitle always gets. `book` is asked for the rules at each run, so the user's additions count."""

    def run(work: StepWork, cancel: threading.Event | None) -> None:
        track = _track(work)
        report = work.progress

        def ocr_progress(done: float) -> None:
            if report is not None:
                report(_EXTRACT_SHARE + (1 - _EXTRACT_SHARE) * done)

        with _folder(work.output) as scratch:
            stream = Path(scratch) / "track.sup"
            extract_track(
                mkvextract,
                work.video,
                track.id,
                stream,
                progress=(lambda done: report(_EXTRACT_SHARE * done)) if report is not None else None,
                cancel=cancel,
            )
            cues = read_pgs(stream, work.language, tesseract, progress=ocr_progress, cancel=cancel)
        write_cues(work.output, fix_ocr(cues, work.language, book()), language=work.language)

    return run


def track_cues(
    mkvextract: Path, video: Path, track: Track, language: Language | None, cancel: threading.Event | None = None
) -> list[Cue]:
    """The lines of a text track of the video, to look at: read once taken out, nothing kept. Raises `ExtractError`
    when the track cannot be taken out and `ValueError` when it is no subtitle."""
    with tempfile.TemporaryDirectory(prefix="showrunner-", ignore_cleanup_errors=True) as scratch:
        extracted = Path(scratch) / f"track.{track_format(track)}"
        extract_track(mkvextract, video, track.id, extracted, cancel=cancel)
        return read_cues(extracted, language)


def _track(work: StepWork) -> Track:
    if work.track is None:
        raise ValueError("reading a track needs the track")
    return work.track


def _folder(output: Path) -> tempfile.TemporaryDirectory[str]:
    """A scratch folder beside the result, so the file moved into place is on the same disk; removed at the end."""
    return tempfile.TemporaryDirectory(dir=output.parent, prefix="reading-", ignore_cleanup_errors=True)
