from __future__ import annotations

from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import SubtitleFile
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.subtitles import FinishedSubtitle, ReferenceTrack, Source, Step, StepKind, SubtitlePlan
from showrunner.ui.quick.jobs import beside_text, reason_text, subtitle_phases

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


def test_a_subtitle_written_beside_has_its_phase_and_names_its_file() -> None:
    paired = SubtitleFile(Path("Show.tr.srt"), Language("tur"))
    replacing = FinishedSubtitle(
        Source.PAIRED, Language("tur"), (Step(StepKind.CLEAN),), "srt", paired, target=paired.path
    )
    translation = FinishedSubtitle(
        Source.TRANSLATION, Language("deu"), (Step(StepKind.TRANSLATE),), "srt", target=Path("Show.de.srt")
    )
    plan = SubtitlePlan(Path("Show.mkv"), (replacing, translation))
    assert subtitle_phases(plan) == ("translate", "clean", "beside")
    assert beside_text(plan) == [
        "Written in place of Show.tr.srt; an old one that differed went to the Recycle Bin.",
        "Written beside the video: Show.de.srt.",
    ]
    assert reason_text("beside-exists: Show.de.srt").startswith("Show.de.srt already lies beside the video")
