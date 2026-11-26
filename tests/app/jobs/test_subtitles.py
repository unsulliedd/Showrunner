"""The subtitle step of a job: each step's result kept by the stamps of what it was made from, reused by a later run or
a resume while those hold, and work no engine can do left out while the file's other changes go on."""

from __future__ import annotations

import os
import threading
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar

import pytest

from showrunner.app.jobs import stages as stages_module
from showrunner.app.jobs.preview import preview
from showrunner.app.jobs.results import KEEP_DAYS, ResultStore
from showrunner.app.jobs.run import create_job, run_job
from showrunner.app.jobs.stages import (
    CleanupSets,
    MuxStage,
    PlanState,
    Stage,
    StagePlan,
    SubtitlesStage,
    TracksStage,
    pipeline,
    subtitle_phases,
)
from showrunner.app.jobs.store import JobStore, StepState
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackKind, VideoProperties
from showrunner.stages.subtitles import (
    Approval,
    Output,
    RuleSetUse,
    StepKind,
    SubtitlePlan,
    SubtitlesOptions,
    SyncEngine,
    Wanted,
)
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


# Beside the video

ONLY_CLEAN = SubtitlesOptions(cleanup={"Hearing impaired": RuleSetUse.USED})


class Bin:
    """Stands in for the Recycle Bin: moves the files into a folder; `kill` makes the process die right after."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.kill = False

    def __call__(self, paths: Sequence[Path]) -> None:
        self.folder.mkdir(exist_ok=True)
        for path in paths:
            path.rename(self.folder / path.name)
        if self.kill:
            self.kill = False
            raise Killed


def beside(output: Output) -> Profile:
    """Cleanup alone, written beside the video, with no track choice: nothing else asks for a new file."""
    return Profile.defaults("Test").with_options("subtitles", replace(ONLY_CLEAN, output=output))


def beside_stages(engines: Engines, results: ResultStore, recycle: Bin) -> tuple[Stage, ...]:
    subtitles = SubtitlesStage(results, dict.fromkeys(ENGINES, engines), CLEANUP, recycle=recycle)
    return (TracksStage(), subtitles)


def texts(path: Path) -> list[str]:
    return [cue.text for cue in read_cues(path)]


def test_replacing_writes_the_subtitle_alone_and_recycles_the_original(setup, tmp_path: Path) -> None:
    item, _, engines, results = setup
    profile, recycle = beside(Output.REPLACE), Bin(tmp_path / "bin")
    given = beside_stages(engines, results, recycle)
    (file,) = preview([item], profile, given).files
    # No stage here can write a new file, and none is needed.
    assert [(plan.stage, plan.needs_remux) for plan in file.writes] == [("subtitles", False)]
    assert run(JobStore(tmp_path / "jobs.sqlite3"), item, profile, given) == (StepState.DONE, "")
    assert texts(item.subtitles[0].path) == ["MERHABA"]
    assert texts(tmp_path / "bin" / item.subtitles[0].path.name) == ["merhaba"]


def test_a_new_file_is_written_beside_the_original(setup, tmp_path: Path) -> None:
    item, _, engines, results = setup
    profile = beside(Output.NEW_FILE)
    assert run(JobStore(tmp_path / "jobs.sqlite3"), item, profile, beside_stages(engines, results, Bin(tmp_path))) == (
        StepState.DONE,
        "",
    )
    assert texts(tmp_path / "Show Name - S01E01_cleaned.tr.srt") == ["MERHABA"]
    assert texts(item.subtitles[0].path) == ["merhaba"]


def test_a_crash_after_the_recycle_is_finished_by_the_resume(setup, tmp_path: Path) -> None:
    item, _, engines, results = setup
    profile, recycle = beside(Output.REPLACE), Bin(tmp_path / "bin")
    store = JobStore(tmp_path / "jobs.sqlite3")
    given = beside_stages(engines, results, recycle)
    job = create_job(store, preview([item], profile, given), profile, given)
    recycle.kill = True
    with pytest.raises(Killed):
        run_job(store, job, given, read=lambda path: item.file)
    original = item.subtitles[0].path
    # The original is in the Recycle Bin and the checked copy waits beside it under its hidden name.
    assert not original.exists()
    assert store.load(job).steps[0].state is StepState.RUNNING
    (record,) = run_job(store, job, given, read=lambda path: item.file).steps
    assert record.state is StepState.DONE
    assert texts(original) == ["MERHABA"]
    assert engines.ran == {StepKind.CLEAN: 1}
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_a_subtitle_written_before_the_step_was_recorded_is_left_as_it_is(setup, tmp_path: Path) -> None:
    item, _, engines, results = setup
    stage = beside_stages(engines, results, Bin(tmp_path / "bin"))[1]
    plan = stage.plan(item, beside(Output.NEW_FILE))
    assert stage.apply(plan, None).ok
    # Run again, as a resume runs a step that was running when the app stopped.
    assert stage.apply(plan, None).ok
    assert texts(tmp_path / "Show Name - S01E01_cleaned.tr.srt") == ["MERHABA"]


def test_a_file_in_the_way_fails_the_step_and_stays(setup, tmp_path: Path) -> None:
    item, _, engines, results = setup
    stage = beside_stages(engines, results, Bin(tmp_path / "bin"))[1]
    plan = stage.plan(item, beside(Output.NEW_FILE))
    in_the_way = tmp_path / "Show Name - S01E01_cleaned.tr.srt"
    write_cues(in_the_way, [Cue(1.0, 2.0, "mine")])
    result = stage.apply(plan, None)
    assert not result.ok
    assert result.message.startswith("beside-exists")
    assert texts(in_the_way) == ["mine"]


def test_a_failed_check_fails_the_step_and_keeps_the_original(setup, tmp_path: Path, monkeypatch) -> None:
    item, _, engines, results = setup
    recycle = Bin(tmp_path / "bin")
    stage = beside_stages(engines, results, recycle)[1]
    plan = stage.plan(item, beside(Output.REPLACE))
    monkeypatch.setattr(
        "showrunner.stages.subtitles.beside.shutil.copyfile",
        lambda source, destination: write_cues(destination, [Cue(1.0, 2.0, "torn")]),
    )
    result = stage.apply(plan, None)
    assert (result.ok, result.message.split(":")[0]) == (False, "beside-check")
    assert texts(item.subtitles[0].path) == ["merhaba"]
    assert not recycle.folder.exists()


def test_mux_adds_the_paired_file_and_not_a_subtitle_written_beside(setup) -> None:
    item, profile, _, results = setup
    into = mux_stage(results, ENGINES).plan(item, profile.with_options("subtitles", ONLY_CLEAN))
    assert into.plan.tracks[-1].content is not None
    tracks_add = profile.with_options("subtitles", replace(ONLY_CLEAN, output=Output.REPLACE))
    mux = mux_stage(results, ENGINES).plan(item, tracks_add)
    # Tracks still adds the file, which the subtitle stage has replaced by the time Mux reads it.
    assert mux.plan.tracks[-1].content is None
    assert mux.plan.added == item.subtitles
    # With no track choice, a subtitle written beside asks Mux for nothing.
    assert mux_stage(results, ENGINES).plan(item, beside(Output.REPLACE)).state is PlanState.UNCHANGED


def test_a_second_run_after_a_new_file_run_has_nothing_to_do(setup, tmp_path: Path) -> None:
    item, _, engines, results = setup
    profile = beside(Output.NEW_FILE)
    given = beside_stages(engines, results, Bin(tmp_path / "bin"))
    assert run(JobStore(tmp_path / "jobs.sqlite3"), item, profile, given) == (StepState.DONE, "")
    written = SubtitleFile(tmp_path / "Show Name - S01E01_cleaned.tr.srt", Language("tur"))
    again = replace(item, subtitles=(*item.subtitles, written))
    (file,) = preview([again], profile, given).files
    subtitles = file.plan_for("subtitles")
    assert subtitles is not None
    assert (subtitles.state, file.writes) == (PlanState.UNCHANGED, ())
    assert [f.target for f in subtitles.plan.written_earlier] == [written.path]


def embedded_setup(setup):
    """The English text track of the video, wanted and cleaned; the paired Turkish file stays out of it."""
    item, profile, engines, results = setup
    options = replace(WORK, sync=SyncEngine.AS_IT_IS, languages={"en": Wanted.WANTED})
    return item, profile.with_options("subtitles", options), engines, results


def test_an_embedded_text_track_in_a_wanted_language_is_read_and_cleaned(setup, tmp_path: Path) -> None:
    item, profile, engines, results = embedded_setup(setup)
    given = stages(engines, results)
    work = SubtitlesStage(results, dict.fromkeys(ENGINES, engines), CLEANUP).plan(item, profile).plan
    assert isinstance(work, SubtitlePlan)
    embedded = next(f for f in work.finished if f.track is not None)
    assert run(JobStore(tmp_path / "jobs.sqlite3"), item, profile, given) == (StepState.DONE, "")
    assert read_cues(results.final(work, embedded)) == [Cue(1.0, 2.0, "HELLO")]
    # Taking the track out ran once for the embedded subtitle, and the paired file was cleaned beside it.
    assert (engines.ran[StepKind.READ], engines.ran[StepKind.CLEAN]) == (1, 2)


def test_the_reference_is_read_once_and_a_phase_reports_its_own_share(setup, tmp_path: Path) -> None:
    item, profile, engines, results = setup
    stage = SubtitlesStage(results, dict.fromkeys(ENGINES, engines), CLEANUP)
    plan = stage.plan(item, profile)
    assert isinstance(plan.plan, SubtitlePlan)
    phases = subtitle_phases(plan.plan)
    assert phases == ("reference", "clean", "sync")
    seen: list[float] = []
    assert stage.apply(plan, None, seen.append).ok
    # Each of the three phases is a third of the step: the reference read, the cleaning, the sync.
    assert seen == [pytest.approx(x) for x in (1 / 3, 2 / 3, 1.0)]
    assert engines.ran == {StepKind.READ: 1, StepKind.CLEAN: 1, StepKind.SYNC: 1}


def test_the_reference_is_kept_by_the_rules_that_read_it(setup) -> None:
    item, profile, engines, results = setup
    work = SubtitlesStage(results, dict.fromkeys(ENGINES, engines), CLEANUP).plan(item, profile).plan
    assert isinstance(work, SubtitlePlan)
    assert results.reference(work, "a") != results.reference(work, "b")
    assert results.reference(work) == results.reference(work, "")


def test_a_reference_read_by_ocr_is_read_again_when_the_way_of_reading_changes(
    setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, engines, results = setup
    stage = SubtitlesStage(results, dict.fromkeys(ENGINES, engines), CLEANUP)
    before = stage._ocr_rules(Language("eng"))
    monkeypatch.setattr(stages_module, "READING", "another way")
    assert stage._ocr_rules(Language("eng")) != before


def test_a_reference_read_by_ocr_is_read_again_when_another_model_is_installed(setup, tmp_path: Path) -> None:
    _, _, engines, results = setup
    model = tmp_path / "ocr" / "tessdata" / "eng.traineddata"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fast")
    stage = SubtitlesStage(results, dict.fromkeys(ENGINES, engines), CLEANUP, tesseract=tmp_path / "ocr" / "tesseract")
    english, turkish = stage._ocr_rules(Language("eng")), stage._ocr_rules(Language("tur"))
    model.write_bytes(b"the best one")
    assert stage._ocr_rules(Language("eng")) != english
    # Only the model of the language read counts.
    assert stage._ocr_rules(Language("tur")) == turkish


def test_the_pipeline_has_an_engine_for_each_program_it_found(tmp_path: Path) -> None:
    def reads(programs: Programs, tesseract: Path | None) -> tuple[StepKind, ...]:
        (subtitles,) = (s for s in pipeline(programs, None, tesseract=tesseract) if isinstance(s, SubtitlesStage))
        return subtitles.available

    assert StepKind.READ not in reads(Programs(), None)
    assert StepKind.READ in reads(Programs(mkvextract=Path("mkvextract")), None)
    assert StepKind.OCR not in reads(Programs(mkvextract=Path("mkvextract")), None)
    # Tesseract alone cannot take a track out of the video.
    assert StepKind.OCR not in reads(Programs(), tmp_path / "tesseract")
    assert StepKind.OCR in reads(Programs(mkvextract=Path("mkvextract")), tmp_path / "tesseract")


def test_the_progress_of_a_file_never_goes_back_across_its_subtitles(setup) -> None:
    item, profile, _engines, results = setup

    class Translating(Engines):
        def __call__(self, work: StepWork, cancel: threading.Event | None) -> None:
            if work.step.kind is StepKind.TRANSLATE:
                write_cues(work.output, [Cue(1.0, 2.0, "Hallo")])
            else:
                super().__call__(work, cancel)

    both = profile.with_options("subtitles", replace(WORK, languages={"de": Wanted.WANTED}))
    stage = SubtitlesStage(results, dict.fromkeys(StepKind, Translating()), CLEANUP)
    plan = stage.plan(item, both)
    assert isinstance(plan.plan, SubtitlePlan)
    assert len(plan.plan.finished) == 2  # the paired file, synced, and a translation
    seen: list[float] = []
    stage.apply(plan, None, seen.append)
    assert seen == sorted(seen)
    assert seen[-1] == pytest.approx(1.0)
