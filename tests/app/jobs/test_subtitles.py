"""The subtitle step of a job: each step's result kept by the stamps of what it was made from, reused by a later run or
a resume while those hold, and work no engine can do left out while the file's other changes go on."""

from __future__ import annotations

import os
import threading
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar

import pytest

from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.results import KEEP_DAYS, ResultStore
from showrunner.app.jobs.run import create_job, run_job
from showrunner.app.jobs.stages import CleanupSets, MuxStage, PlanState, Stage, StagePlan, SubtitlesStage, TracksStage
from showrunner.app.jobs.store import JobStore, StepState
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackKind, VideoProperties
from showrunner.stages.subtitles import Approval, RuleSetUse, StepKind, SubtitlePlan, SubtitlesOptions, SyncEngine
from showrunner.stages.subtitles.work import StepWork
from showrunner.stages.tracks import PairedFile, TracksOptions
from showrunner.tools.cleanit import RuleDef, RuleSet
from showrunner.tools.probe import Programs

TRACKS = (
    Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080)),
    Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), audio=AudioProperties(6)),
    Track(2, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties()),
)
CLEANUP = CleanupSets({"Hearing impaired": RuleSet("Hearing impaired", (RuleDef(name="rule", patterns=("x",)),))})
WORK = SubtitlesOptions(cleanup={"Hearing impaired": RuleSetUse.USED}, sync=SyncEngine.FFSUBSYNC)
# Every kind of work but the wait for approval, which nothing can give yet.
ENGINES = tuple(kind for kind in StepKind if kind is not StepKind.APPROVAL)


class Killed(BaseException):
    """Stands in for the process dying: no `except Exception` catches it."""


class Engines:
    """Stand-ins for the engines: reading writes one cue, cleaning upper-cases, syncing moves every cue a second."""

    def __init__(self) -> None:
        self.ran: Counter[StepKind] = Counter()
        self.kill: StepKind | None = None

    def __call__(self, work: StepWork, cancel: threading.Event | None) -> None:
        kind = work.step.kind
        if kind is self.kill:
            raise Killed
        self.ran[kind] += 1
        if kind is StepKind.READ:
            write_cues(work.output, [Cue(1.0, 2.0, "Hello")])
            return
        assert work.source is not None
        cues = read_cues(work.source)
        if kind is StepKind.CLEAN:
            cues = [replace(cue, text=cue.text.upper()) for cue in cues]
        else:
            assert work.reference is not None
            assert work.reference.exists()
            cues = [replace(cue, start=cue.start + 1, end=cue.end + 1) for cue in cues]
        write_cues(work.output, cues)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[MediaItem, Profile, Engines, ResultStore]:
    video = tmp_path / "Show Name - S01E01.mkv"
    video.write_bytes(b"matroska")
    paired = tmp_path / "Show Name - S01E01.tr.srt"
    paired.write_text("1\n00:00:01,000 --> 00:00:02,000\nmerhaba\n", encoding="utf-8")
    subtitle = SubtitleFile(paired, Language("tur"))
    item = MediaItem(Episode("Show Name", 1, 1), MediaFile(video, "matroska", tracks=TRACKS), (subtitle,))
    profile = (
        Profile.defaults("Test")
        .with_options("tracks", TracksOptions(add_paired=[PairedFile.of(subtitle)]))
        .with_options("subtitles", WORK)
    )
    return item, profile, Engines(), ResultStore(tmp_path / "results")


@dataclass(frozen=True)
class Remuxes:
    """Stands in for Mux, so the preview has a stage that can write the new file the subtitles ask for; the tests
    stop before it."""

    id: ClassVar[str] = "mux"
    remuxes: ClassVar[bool] = True

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        return StagePlan(self.id, PlanState.UNCHANGED)


def stages(engines: Engines, results: ResultStore, kinds: tuple[StepKind, ...] = ENGINES) -> tuple[Stage, ...]:
    return (TracksStage(), SubtitlesStage(results, runners=dict.fromkeys(kinds, engines), cleanup=CLEANUP), Remuxes())  # type: ignore[return-value]


def run(store: JobStore, item: MediaItem, profile: Profile, given: tuple[Stage, ...]) -> tuple[StepState, str]:
    job = create_job(store, preview([item], profile, given), profile, given)
    try:
        (record,) = run_job(store, job, given, read=lambda path: item.file).steps
    except Killed:
        (step,) = store.load(job).steps
        return step.state, step.message
    return record.state, record.message


def final(item: MediaItem, profile: Profile, results: ResultStore) -> Path:
    work = SubtitlesStage(results, dict.fromkeys(ENGINES, Engines()), CLEANUP).plan(item, profile).plan
    assert isinstance(work, SubtitlePlan)
    return results.final(work, work.finished[0])


def mux_stage(results: ResultStore, available: tuple[StepKind, ...]) -> MuxStage:
    return MuxStage(Path("mkvmerge"), Programs(), results=results, available=available, cleanup=CLEANUP)


def test_work_no_engine_can_do_is_left_out_and_the_track_change_still_remuxes(setup) -> None:
    item, profile, engines, results = setup
    some = (StepKind.READ, StepKind.CLEAN)
    subtitles = SubtitlesStage(results, dict.fromkeys(some, engines), CLEANUP).plan(item, profile)
    assert subtitles.state is PlanState.UNCHANGED
    assert not subtitles.writes
    work = subtitles.plan
    assert isinstance(work, SubtitlePlan)
    assert (work.finished, work.reference) == ((), None)
    assert [f.missing for f in work.left_out] == [(StepKind.SYNC,)]
    # The Turkish file the Tracks choice adds still goes into the new file, as it is.
    mux = mux_stage(results, some).plan(item, profile)
    assert mux.writes
    assert mux.plan.tracks[-1].content is None
    assert mux.plan.added == item.subtitles
    # Apply writes the remux alone: no subtitle step comes before it to fail the file.
    given = (TracksStage(), SubtitlesStage(results, dict.fromkeys(some, engines), CLEANUP), mux_stage(results, some))
    (file,) = preview([item], profile, given).files
    assert [plan.stage for plan in file.writes] == ["mux"]


def test_a_wait_for_approval_nothing_can_give_leaves_the_subtitle_out(setup) -> None:
    item, profile, engines, results = setup
    waits = profile.with_options("subtitles", replace(WORK, approval=Approval.EVERY))
    work = SubtitlesStage(results, dict.fromkeys(ENGINES, engines), CLEANUP).plan(item, waits).plan
    assert isinstance(work, SubtitlePlan)
    assert [f.missing for f in work.left_out] == [(StepKind.APPROVAL,)]
    # With approval available the subtitle is planned and waits.
    work = SubtitlesStage(results, dict.fromkeys(StepKind, engines), CLEANUP).plan(item, waits).plan
    assert isinstance(work, SubtitlePlan)
    assert work.waits


def test_results_are_kept_and_a_second_run_reuses_them(setup, tmp_path: Path) -> None:
    item, profile, engines, results = setup
    store = JobStore(tmp_path / "jobs.sqlite3")
    assert run(store, item, profile, stages(engines, results)) == (StepState.DONE, "")
    assert read_cues(final(item, profile, results)) == [Cue(2.0, 3.0, "MERHABA")]
    assert engines.ran == {StepKind.READ: 1, StepKind.CLEAN: 1, StepKind.SYNC: 1}
    assert run(store, item, profile, stages(engines, results)) == (StepState.DONE, "")
    assert engines.ran == {StepKind.READ: 1, StepKind.CLEAN: 1, StepKind.SYNC: 1}


def test_a_changed_setting_runs_only_the_steps_from_it_on(setup, tmp_path: Path) -> None:
    item, profile, engines, results = setup
    store = JobStore(tmp_path / "jobs.sqlite3")
    run(store, item, profile, stages(engines, results))
    alass = profile.with_options("subtitles", replace(WORK, sync=SyncEngine.ALASS))
    run(store, item, alass, stages(engines, results))
    assert engines.ran == {StepKind.READ: 1, StepKind.CLEAN: 1, StepKind.SYNC: 2}


def test_a_changed_paired_file_runs_its_steps_again(setup, tmp_path: Path) -> None:
    item, profile, engines, results = setup
    store = JobStore(tmp_path / "jobs.sqlite3")
    run(store, item, profile, stages(engines, results))
    item.subtitles[0].path.write_text("1\n00:00:05,000 --> 00:00:06,000\nhosca kal\n", encoding="utf-8")
    run(store, item, profile, stages(engines, results))
    assert engines.ran == {StepKind.READ: 1, StepKind.CLEAN: 2, StepKind.SYNC: 2}
    assert read_cues(final(item, profile, results)) == [Cue(6.0, 7.0, "HOSCA KAL")]


def test_a_resume_after_a_crash_reuses_what_was_finished(setup, tmp_path: Path) -> None:
    item, profile, engines, results = setup
    store = JobStore(tmp_path / "jobs.sqlite3")
    given = stages(engines, results)
    job = create_job(store, preview([item], profile, given), profile, given)
    engines.kill = StepKind.SYNC
    with pytest.raises(Killed):
        run_job(store, job, given, read=lambda path: item.file)
    assert store.load(job).steps[0].state is StepState.RUNNING
    engines.kill = None
    (record,) = run_job(store, job, given, read=lambda path: item.file).steps
    assert (record.state, record.detail) == (StepState.DONE, 2)  # the reference and the cleanup were kept
    assert engines.ran == {StepKind.READ: 1, StepKind.CLEAN: 1, StepKind.SYNC: 1}


def test_a_result_cut_short_is_not_reused(setup) -> None:
    item, profile, _engines, results = setup
    output = final(item, profile, results)
    output.parent.mkdir(parents=True)
    output.write_text("half", encoding="utf-8")
    assert not results.kept(output, [item.file.path])
    results.keep(output, [item.file.path])
    assert results.kept(output, [item.file.path])
    item.file.path.write_bytes(b"matroska, written again")
    assert not results.kept(output, [item.file.path])


def test_folders_unused_for_long_are_pruned(tmp_path: Path) -> None:
    results = ResultStore(tmp_path / "results")
    results.prune()  # no folder yet
    old, recent = tmp_path / "results" / "old", tmp_path / "results" / "recent"
    for folder in (old, recent):
        folder.mkdir(parents=True)
        (folder / "result.srt").write_text("", encoding="utf-8")
    now = os.stat(recent).st_mtime
    os.utime(old, (now - (KEEP_DAYS + 1) * 86400,) * 2)
    results.prune(now)
    assert sorted(p.name for p in (tmp_path / "results").iterdir()) == ["recent"]


def test_the_mux_reads_the_final_result(setup) -> None:
    item, profile, _engines, results = setup
    mux = mux_stage(results, ENGINES).plan(item, profile)
    assert mux.plan.tracks[-1].content == final(item, profile, results)
    assert mux.plan.added == item.subtitles  # moved away with the original once the new file is in place
