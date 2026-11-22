"""The clean step on files, and the OCR fixes."""

from __future__ import annotations

from pathlib import Path

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.stages.subtitles import Step, StepKind
from showrunner.stages.subtitles.clean import clean_runner, fix_ocr
from showrunner.stages.subtitles.work import StepWork
from showrunner.tools.cleanit import OCR_EXTRA, OCR_SET, RuleBook, RuleDef, RuleSet, builtin_sets

ENGLISH = Language("eng")
CUES = [
    Cue(1, 2, "(DOOR SLAMS)\nWhere were you?"),
    Cue(3, 4, "Visit opensubtitles.org"),
    Cue(5, 6, r"{\i1}Well,  then{\i0}"),
]


def book(*own: RuleSet) -> RuleBook:
    return RuleBook({**builtin_sets(), **{s.name: s for s in own}})


def work(tmp_path: Path, sets: tuple[str, ...], language: Language | None = ENGLISH) -> StepWork:
    source = tmp_path / "in.srt"
    write_cues(source, CUES)
    return StepWork(
        Step(StepKind.CLEAN, sets), tmp_path / "video.mkv", source, None, language, None, tmp_path / "out" / "out.srt"
    )


def test_the_clean_step_writes_the_cues_the_chosen_sets_leave(tmp_path: Path) -> None:
    given = work(tmp_path, ("no-sdh", "no-spam", "tidy"))
    given.output.parent.mkdir()
    clean_runner(book)(given, None)
    assert read_cues(given.output) == [Cue(1, 2, "Where were you?"), Cue(5, 6, r"{\i1}Well, then{\i0}")]


def test_the_runner_asks_for_the_rules_when_it_runs(tmp_path: Path) -> None:
    given = work(tmp_path, ("mine",))
    given.output.parent.mkdir()
    calls = []

    def current() -> RuleBook:
        calls.append(1)
        return book(RuleSet("mine", (RuleDef("r", ("Visit",), replacement="Go"),)))

    clean_runner(current)(given, None)
    assert len(calls) == 1
    assert read_cues(given.output)[1].text == "Go opensubtitles.org"


def test_an_ass_subtitle_keeps_its_styles(tmp_path: Path) -> None:
    source = tmp_path / "in.ass"
    write_cues(source, [Cue(1, 2, "(HEY)\nhi", "Sign")])
    out = tmp_path / "out.ass"
    given = StepWork(Step(StepKind.CLEAN, ("no-sdh",)), tmp_path / "v.mkv", source, None, ENGLISH, None, out)
    clean_runner(book)(given, None)
    assert [(c.text, c.style) for c in read_cues(out)] == [("hi", "Sign")]


def test_the_ocr_fixes_are_cleanits_set_for_the_language_and_the_users_additions() -> None:
    mine = RuleSet(OCR_EXTRA, (RuleDef("mine", ("Hte",), replacement="The"),))
    cues = [Cue(1, 2, "Wait… what is that?"), Cue(3, 4, "Hte end")]
    fixed = fix_ocr(cues, ENGLISH, book(mine))
    assert [c.text for c in fixed] == ["Wait... what is that?", "The end"]
    assert OCR_SET in builtin_sets()
    # No rule set of a place is involved: the fixes apply to every picture subtitle.
    assert fix_ocr(cues, ENGLISH, RuleBook({})) == cues
