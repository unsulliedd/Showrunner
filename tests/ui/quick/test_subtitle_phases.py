from __future__ import annotations

from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.subtitles import FinishedSubtitle, ReferenceTrack, Source, Step, StepKind, SubtitlePlan
from showrunner.ui.quick.jobs import reason_text, subtitle_phases

PGS = Track(2, TrackKind.SUBTITLE, "S_HDMV/PGS", Language("eng"), subtitle=SubtitleProperties(text_based=False))


def test_a_file_shows_one_phase_per_kind_of_work_in_the_order_it_runs() -> None:
    translation = FinishedSubtitle(
        Source.TRANSLATION, Language("deu"), (Step(StepKind.TRANSLATE), Step(StepKind.CLEAN)), "srt", waits=True
    )
    paired = FinishedSubtitle(Source.PAIRED, Language("tur"), (Step(StepKind.CLEAN), Step(StepKind.SYNC)), "srt")
    plan = SubtitlePlan(Path("a.mkv"), (paired, translation), ReferenceTrack(PGS))
    assert subtitle_phases(plan) == ("ocr", "translate", "clean", "sync", "approval")


def test_a_step_without_its_engine_is_worded() -> None:
    assert reason_text("not-available: sync").startswith("Sync is not available in this version yet")
    assert reason_text("not-available: something else") == "not-available: something else"
