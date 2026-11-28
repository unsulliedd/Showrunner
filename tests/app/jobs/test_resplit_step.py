"""The re-split step of a job: by timing it needs no server; with AI, a re-split where a window went by timing is not
kept, so the next run asks for that window again and reuses the others."""

from __future__ import annotations

import shutil
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from showrunner.app.jobs.results import ResultStore
from showrunner.app.jobs.stages import CleanupSets, SubtitlesStage
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import SubtitleProperties, Track, TrackKind, VideoProperties
from showrunner.stages.subtitles import AiModels, Lines, Output, StepKind, SubtitlePlan, SubtitlesOptions, SyncEngine
from showrunner.stages.subtitles.resplit_ai import resplit_runner
from showrunner.stages.subtitles.work import StepWork
from showrunner.tools.ai import AiError, ErrorKind

TRACKS = (
    Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080)),
    Track(1, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties()),
)
AI = AiModels("sample:9b", ("sample:9b",), window=2)
OPTIONS = SubtitlesOptions(sync=SyncEngine.FFSUBSYNC, lines=Lines.WITH_AI, output=Output.NEW_FILE)


def reading(work: StepWork, cancel: threading.Event | None) -> None:
    write_cues(work.output, [Cue(2.0 * n, 2.0 * n + 2, f"English {n}") for n in range(4)])


def in_sync(work: StepWork, cancel: threading.Event | None) -> None:
    assert work.source is not None
    shutil.copyfile(work.source, work.output)


def item(tmp_path: Path) -> MediaItem:
    video = tmp_path / "Show Name - S01E01.mkv"
    video.write_bytes(b"matroska")
    paired = tmp_path / "Show Name - S01E01.tr.srt"
    write_cues(paired, [Cue(4.0 * n, 4.0 * n + 4, f"bir{n} iki{n} üç{n}") for n in range(2)])
    media = MediaFile(video, "matroska", tracks=TRACKS)
    return MediaItem(Episode("Show Name", 1, 1), media, subtitles=(SubtitleFile(paired, Language("tur")),))


def stage(tmp_path: Path, backend: Any, ai: AiModels | None = AI) -> SubtitlesStage:
    runners = {StepKind.READ: reading, StepKind.SYNC: in_sync, StepKind.RESPLIT: resplit_runner(lambda: backend)}
    return SubtitlesStage(ResultStore(tmp_path / "results"), runners, CleanupSets(), ai=ai)


def test_by_timing_runs_without_a_server(tmp_path: Path) -> None:
    profile = Profile.defaults("Test").with_options("subtitles", replace(OPTIONS, lines=Lines.BY_TIMING))
    found = stage(tmp_path, None, ai=None)
    assert found.apply(found.plan(item(tmp_path), profile), None).ok
    written = tmp_path / "Show Name - S01E01_cleaned.tr.srt"
    assert [cue.text for cue in read_cues(written)] == ["bir0", "iki0 üç0", "bir1", "iki1 üç1"]


def test_a_resplit_with_a_window_by_timing_is_not_kept_and_the_next_run_asks_for_it_again(
    tmp_path: Path, splitter: Any
) -> None:
    video, profile = item(tmp_path), Profile.defaults("Test").with_options("subtitles", OPTIONS)

    def first_cue(count: int, words: list[str]) -> str:
        """Every word on the first cue."""
        return "\n".join([f"[1]\n{' '.join(words)}", *(f"[{number}]" for number in range(2, count + 1))])

    timeout = splitter(first_cue, fail=lambda asked: AiError(ErrorKind.TIMEOUT) if asked == 2 else None)
    first = stage(tmp_path, timeout)
    plan = first.plan(video, profile)
    assert first.apply(plan, None).ok
    work = plan.plan
    assert isinstance(work, SubtitlePlan)
    (turkish,) = work.finished
    report = first.results.resplit_report(work, turkish)
    assert report is not None
    assert report.by_timing == (2,)
    # The first window as the model said, the second by timing.
    cues = read_cues(first.results.final(work, turkish))
    assert [(cue.start, cue.end, cue.text) for cue in cues] == [
        (0.0, 4.0, "bir0 iki0 üç0"),
        (4.0, 6.0, "bir1"),
        (6.0, 8.0, "iki1 üç1"),
    ]
    backend = splitter()
    again = stage(tmp_path, backend)
    assert again.apply(again.plan(video, profile), None).ok
    assert len(backend.asked) == 1
    report = again.results.resplit_report(work, turkish)
    assert report is not None
    assert (report.by_timing, report.reused) == ((), 1)
