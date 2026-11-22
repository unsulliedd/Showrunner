"""The cleanup engine: the rules of the chosen sets applied to the cues of a subtitle, and the OCR fixes for the text a
picture subtitle was read into."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.stages.subtitles.work import Runner, StepWork
from showrunner.tools.cleanit import RuleBook, clean_cues, kept_cues


def clean_runner(book: Callable[[], RuleBook]) -> Runner:
    """The runner of the clean step. `book` is asked for the rule sets at each run, so it reads what the files hold
    then. A cleaning is a matter of milliseconds, so it is not interrupted by a cancel; the job stops before its next
    step."""

    def run(work: StepWork, cancel: threading.Event | None) -> None:
        if work.source is None:
            raise ValueError("cleaning needs the subtitle it works on")
        compiled = book().compile(work.step.sets, work.language)
        cues = kept_cues(clean_cues(read_cues(work.source, work.language), compiled))
        write_cues(work.output, cues, like=work.source, language=work.language)

    return run


def fix_ocr(cues: Sequence[Cue], language: Language | None, book: RuleBook) -> list[Cue]:
    """The cues of a picture subtitle after the OCR fixes: cleanit's set for the language and the user's additions.
    They are always applied to text read by OCR, whatever sets a place chooses."""
    return kept_cues(clean_cues(cues, book.ocr(language)))
