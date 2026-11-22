"""The sync step of a job: its result and what it found are kept and reused, a changed setting syncs again, and the
pipeline plans only the sync the engines it found can do."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest

from showrunner.app.jobs.results import ResultStore
from showrunner.app.jobs.stages import CleanupSets, SubtitlesStage, sync_runners
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import SubtitleProperties, Track, TrackKind, VideoProperties
from showrunner.stages.subtitles import Output, StepKind, SubtitlePlan, SubtitlesOptions, SyncEngine
from showrunner.stages.subtitles.sync import sync_runner
from showrunner.stages.subtitles.work import StepWork
from showrunner.stages.tracks import PairedFile, TracksOptions
from showrunner.tools.sync import IN_SYNC_BELOW, UNSURE_BELOW, Setting, SyncOutcome, SyncRequest
from showrunner.ui.quick.review import left_as_it_was

TRACKS = (
    Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080)),
    Track(1, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties()),
)


class Engine:
    name: ClassVar[str] = "ffsubsync"
    settings: ClassVar[tuple[Setting, ...]] = ()
    defaults: ClassVar[dict[str, str]] = {IN_SYNC_BELOW: "0.3", UNSURE_BELOW: "0.1"}
    audio = True

    def __init__(self) -> None:
        self.offset, self.score, self.calls = 2.0, 0.5, 0

    def sync(self, request: SyncRequest) -> SyncOutcome:
        self.calls += 1
        write_cues(
            request.output,
            [Cue(c.start + self.offset, c.end + self.offset, c.text) for c in read_cues(request.subtitle)],
        )
        return SyncOutcome(self.offset, score=self.score, length=100.0)


def reading(work: StepWork, cancel: threading.Event | None) -> None:
    write_cues(work.output, [Cue(1.0, 2.0, "Hello")])


@pytest.fixture
def setup(tmp_path: Path) -> tuple[MediaItem, Profile, Engine, SubtitlesStage]:
    video = tmp_path / "Show Name - S01E01.mkv"
    video.write_bytes(b"matroska")
    paired = tmp_path / "Show Name - S01E01.tr.srt"
    write_cues(paired, [Cue(10.0, 12.0, "merhaba")])
    subtitle = SubtitleFile(paired, Language("tur"))
    item = MediaItem(Episode("Show Name", 1, 1), MediaFile(video, "matroska", tracks=TRACKS), (subtitle,))
    options = SubtitlesOptions(sync=SyncEngine.FFSUBSYNC)
    profile = (
        Profile.defaults("Test")
        .with_options("tracks", TracksOptions(add_paired=[PairedFile.of(subtitle)]))
        .with_options("subtitles", options)
    )
    engine = Engine()
    runners = {StepKind.READ: reading, StepKind.SYNC: sync_runner({"ffsubsync": engine})}
    stage = SubtitlesStage(ResultStore(tmp_path / "results"), runners, CleanupSets())
    return item, profile, engine, stage


def apply(stage: SubtitlesStage, item: MediaItem, profile: Profile) -> SubtitlePlan:
    plan = stage.plan(item, profile)
    assert plan.writes
    assert stage.apply(plan, None).ok
    assert isinstance(plan.plan, SubtitlePlan)
    return plan.plan


def test_what_the_step_found_is_kept_and_a_second_run_reuses_it(setup) -> None:
    item, profile, engine, stage = setup
    plan = apply(stage, item, profile)
    (finished,) = plan.finished
    report = stage.results.sync_report(plan, finished)
    assert report is not None
    assert (report.offset, report.in_sync, report.needs_review) == (2.0, False, False)
    assert read_cues(stage.results.final(plan, finished)) == [Cue(12.0, 14.0, "merhaba")]
    apply(stage, item, profile)
    assert engine.calls == 1
    assert stage.results.sync_report(plan, finished) == report


def test_a_changed_engine_setting_or_threshold_syncs_again(setup) -> None:
    item, profile, engine, stage = setup
    apply(stage, item, profile)
    options = profile.for_stage("subtitles")
    for settings in ({"ffsubsync.max_offset": "30"}, {"ffsubsync.max_offset": "30", "ffsubsync.unsure_below": "0.7"}):
        apply(stage, item, profile.with_options("subtitles", replace(options, sync_settings=settings)))
    assert engine.calls == 3
    plan = apply(stage, item, profile.with_options("subtitles", replace(options, sync_settings=settings)))
    report = stage.results.sync_report(plan, plan.finished[0])
    assert report is not None
    assert report.needs_review  # 0.5 is under the 0.7 this place asks for
    assert engine.calls == 3


def test_a_subtitle_in_sync_stays_as_it_is_and_says_so(setup) -> None:
    item, profile, engine, stage = setup
    engine.offset = 0.1
    plan = apply(stage, item, profile)
    (finished,) = plan.finished
    assert stage.results.final(plan, finished).read_bytes() == item.subtitles[0].path.read_bytes()
    report = stage.results.sync_report(plan, finished)
    assert report is not None
    assert report.in_sync


def test_a_finished_subtitle_with_no_sync_has_no_report(setup) -> None:
    item, profile, _engine, stage = setup
    plan = apply(stage, item, profile)
    assert stage.results.sync_report(plan, replace(plan.finished[0], steps=())) is None


def test_the_pipeline_syncs_with_the_engines_it_found() -> None:
    runners, syncs = sync_runners(None)
    assert StepKind.SYNC in runners
    # ffsubsync is installed, but cannot listen without ffmpeg.
    assert syncs == ((SyncEngine.FFSUBSYNC, False),)
    assert sync_runners(Path("ffmpeg"))[1] == ((SyncEngine.FFSUBSYNC, True),)


def test_a_subtitle_that_came_out_as_it_went_in_writes_nothing_beside_the_video(setup, tmp_path: Path) -> None:
    item, profile, engine, stage = setup
    original = item.subtitles[0].path
    kept = original.read_bytes()
    recycled: list[list[Path]] = []
    stage = replace(stage, recycle=recycled.append)
    options = profile.for_stage("subtitles")
    new_file = profile.with_options("subtitles", replace(options, output=Output.NEW_FILE))
    # Found 2 s off: the moved subtitle is written as a new file.
    apply(stage, item, new_file)
    (moved,) = tmp_path.glob("*_cleaned*.srt")
    assert [cue.start for cue in read_cues(moved)] == [12.0]
    moved.unlink()
    # Found in sync: it is the original as it was, so no file is written, and replacing leaves the original alone.
    engine.offset = 0.1
    stage = replace(stage, results=ResultStore(tmp_path / "other"))
    plan = apply(stage, item, new_file)
    assert list(tmp_path.glob("*_cleaned*.srt")) == []
    assert left_as_it_was(plan, plan.finished[0], stage.results)
    apply(stage, item, profile.with_options("subtitles", replace(options, output=Output.REPLACE)))
    assert original.read_bytes() == kept
    assert recycled == []
