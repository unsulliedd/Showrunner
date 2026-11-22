"""What the views say about a sync: what it found, in words, and what a left-out sync lacks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from showrunner.app.library.library import Library
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import Track, TrackKind, VideoProperties
from showrunner.stages.subtitles import Output, StepKind, SubtitlePlan, SubtitlesOptions, SyncEngine, plan_subtitles
from showrunner.stages.subtitles.sync import SyncReport
from showrunner.stages.tracks import PairedFile, TracksOptions
from showrunner.ui.quick import jobs, review, subtitles
from showrunner.ui.quick.review import missing_phases, sync_found
from showrunner.ui.quick.window import WindowController

from .test_choices import open_season, settle
from .test_subtitles_place import row


def report(**changes: Any) -> SyncReport:
    found = {
        "engine": "ffsubsync",
        "offset": -2.4,
        "scale": 1.0,
        "score": 0.4,
        "shift": 2.4,
        "in_sync": False,
        "needs_review": False,
    }
    return SyncReport(**(found | changes))


def test_what_a_sync_found_is_told_in_words() -> None:
    assert sync_found(report()) == "moved -2.40 s"
    assert sync_found(report(offset=0.5, scale=1.001, shift=1.8)) == "moved +0.50 s and stretched by 1.0010"
    assert sync_found(report(offset=0.1, shift=0.1, in_sync=True)) == "already in sync (0.10 s), kept as it is"
    assert sync_found(report(needs_review=True, score=0.05)) == "moved -2.40 s · needs review: score 0.05"


def test_a_sync_against_the_audio_without_its_program_lacks_the_audio_and_another_engine_lacks_itself() -> None:
    video = Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080))
    paired = SubtitleFile(Path("a.tr.srt"), Language("tur"))
    item = MediaItem(None, MediaFile(Path("a.mkv"), "matroska", tracks=(video,)), (paired,))  # type: ignore[arg-type]
    tracks = TracksOptions(add_paired=[PairedFile.of(paired)])
    for engine, kind in ((SyncEngine.FFSUBSYNC, StepKind.AUDIO), (SyncEngine.ALASS, StepKind.SYNC)):
        plan = plan_subtitles(item, SubtitlesOptions(sync=engine), tracks, syncs={SyncEngine.FFSUBSYNC: False})
        (finished,) = plan.left_out
        assert finished.missing == (kind,)
        assert missing_phases(finished) == [kind.value]


def test_the_file_list_says_what_the_last_sync_found(
    engines: WindowController, library: Library, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = engines
    open_season(controller, library, qtbot)
    controller.set_subtitle_choice("output", "new-file")
    controller.set_subtitle_choice("sync", "ffsubsync")
    settle(controller, qtbot)
    (plan,) = controller.subtitles["files"][0]["plan"]
    assert (plan["steps"].split(" → ")[0], plan["found"], plan["review"]) == ("sync", "", False)
    monkeypatch.setattr(subtitles, "kept_sync", lambda work, finished: report(needs_review=True))
    controller.set_subtitle_choice("sync", "ffsubsync")
    controller.set_sync_setting("ffsubsync.unsure_below", "0.9")  # a change, so the place is built again
    settle(controller, qtbot)
    (plan,) = controller.subtitles["files"][0]["plan"]
    assert (plan["found"], plan["review"]) == ("moved -2.40 s · needs review: score 0.40", True)
    assert row(controller, "sync")["note"] == ""


def test_jobs_and_review_say_no_file_was_written_for_a_subtitle_that_came_out_as_it_went_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080))
    paired = SubtitleFile(Path("a.tr.srt"), Language("tur"))
    item = MediaItem(None, MediaFile(Path("a.mkv"), "matroska", tracks=(video,)), (paired,))  # type: ignore[arg-type]
    options = SubtitlesOptions(sync=SyncEngine.FFSUBSYNC, output=Output.NEW_FILE)
    plan = plan_subtitles(item, options, TracksOptions(), syncs={SyncEngine.FFSUBSYNC: True})
    assert [line.endswith("a_cleaned.tr.srt.") for line in jobs.beside_text(plan)] == [True]
    monkeypatch.setattr(jobs, "left_as_it_was", lambda work, finished: True)
    assert jobs.beside_text(plan) == ["a_cleaned.tr.srt not written: the subtitle came out as it went in."]
    monkeypatch.setattr(review, "left_as_it_was", lambda work, finished: True)
    sentences = [r["text"] for r in review._subtitle_lines(_Preview(plan), False) if r["label"] == "Subtitle files"]
    assert sentences == ["Turkish: came out as it went in, so no file is written beside the video."]


class _Preview:
    """Stands in for a file's preview: only the subtitle plan is asked of it."""

    def __init__(self, plan: SubtitlePlan) -> None:
        self._plan = plan

    def plan_for(self, stage: str) -> Any:
        return SimpleNamespace(plan=self._plan)
