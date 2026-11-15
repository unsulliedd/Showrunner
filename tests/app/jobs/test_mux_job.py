"""A remux through the job queue on a real file in `tmp_path`; skipped without ffmpeg and MKVToolNix."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from showrunner.app.jobs.hashing import stamp
from showrunner.app.jobs.preview import FileOutcome, preview
from showrunner.app.jobs.run import create_job, run_job
from showrunner.app.jobs.stages import MetadataStage, MuxStage, TracksStage
from showrunner.app.jobs.store import JobStore, StepState
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.naming import NamingOptions
from showrunner.stages.mux import MuxOptions, MuxResult, apply_mux
from showrunner.stages.tracks import KindTest, TrackMatch, TrackRule, TracksOptions, Verdict
from showrunner.tools.probe import Programs, probe

DROP_FRENCH = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["fre"]), verdict=Verdict.DROP)


class Bin:
    def __init__(self, folder: Path) -> None:
        folder.mkdir()
        self.folder = folder

    def __call__(self, paths: Sequence[Path]) -> None:
        for path in paths:
            path.rename(self.folder / path.name)


@pytest.fixture
def setup(real_episode: Any, tmp_path: Path) -> Any:
    programs = Programs(mkvmerge=real_episode.mkvmerge)
    propedit = real_episode.mkvmerge.with_name(real_episode.mkvmerge.name.replace("mkvmerge", "mkvpropedit"))
    stages = (TracksStage(), MuxStage(real_episode.mkvmerge, programs, recycle=Bin(tmp_path / "bin")))
    stages += (MetadataStage(propedit, programs),)
    profile = Profile.defaults("Test")
    profile = profile.with_options("tracks", TracksOptions(rules=[DROP_FRENCH]))
    profile = profile.with_options("mux", MuxOptions())
    profile = profile.with_options("naming", replace(NamingOptions(), title_template="{show} {episode}"))
    item = MediaItem(
        Episode("Show Name", 1, 1),
        probe(real_episode.video, programs),
        (SubtitleFile(real_episode.subtitle, Language("tur")),),
    )

    def read(path: Path) -> MediaFile:
        return probe(path, programs)

    return SimpleNamespace(stages=stages, profile=profile, item=item, read=read, ep=real_episode)


def test_a_remuxed_file_gets_its_header_from_the_remux_alone(setup: Any, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    planned = preview([setup.item], setup.profile, setup.stages)
    file = planned.files[0]
    assert file.outcome is FileOutcome.CHANGES
    metadata = file.plan_for("metadata")
    assert metadata is not None
    assert metadata.state.value == "changes"  # a new title is planned...
    assert [p.stage for p in file.writes] == ["mux"]  # ...and written by the remux, not by mkvpropedit
    job = create_job(store, planned, setup.profile, setup.stages)
    fractions: list[float] = []
    result = run_job(store, job, setup.stages, read=setup.read, step_progress=lambda _p, _s, f: fractions.append(f))
    assert [r.state for r in result.steps] == [StepState.DONE]
    assert isinstance(result.steps[0].detail, MuxResult)
    assert fractions
    assert probe(setup.ep.video, Programs(mkvmerge=setup.ep.mkvmerge)).title == "Show Name 1"


def test_without_mkvmerge_or_with_mux_blocked_a_file_that_needs_a_remux_is_not_written(setup: Any) -> None:
    no_mux = tuple(s for s in setup.stages if s.id != "mux")
    for file in (
        preview([setup.item], setup.profile, no_mux).files[0],
        preview([setup.item], setup.profile, setup.stages, blocked={"mux"}).files[0],
    ):
        assert file.outcome is FileOutcome.NEEDS_REMUX
        assert file.writes == ()


def test_a_mkvmerge_error_fails_the_step_and_leaves_the_original(setup: Any, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    original = setup.ep.video.read_bytes()
    job = create_job(store, preview([setup.item], setup.profile, setup.stages), setup.profile, setup.stages)
    setup.ep.subtitle.unlink()
    result = run_job(store, job, setup.stages, read=setup.read)
    assert [r.state for r in result.steps] == [StepState.FAILED]
    assert "merge" in result.steps[0].message
    assert setup.ep.video.read_bytes() == original


def test_resume_after_an_interrupted_mux_removes_its_partial_file_and_runs_again(setup: Any, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = create_job(store, preview([setup.item], setup.profile, setup.stages), setup.profile, setup.stages)
    step = store.load(job).steps[0]
    # The app stopped while mkvmerge wrote: the step is still running and half a file lies beside the original.
    store.set_state(job, step.position, StepState.RUNNING)
    partial = step.plan.plan.partial  # type: ignore[attr-defined]
    partial.write_bytes(b"half a file")
    result = run_job(store, job, setup.stages, read=setup.read)
    assert [r.state for r in result.steps] == [StepState.DONE]
    assert not partial.exists()
    assert sorted(p.name for p in setup.ep.video.parent.iterdir()) == ["Show Name - S01E01.mkv"]


def test_a_new_name_is_reported_and_marked_finished(setup: Any, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    profile = setup.profile.with_options("mux", MuxOptions(suffix=" [remux]"))
    planned = preview([setup.item], profile, setup.stages)
    result = run_job(store, create_job(store, planned, profile, setup.stages), setup.stages, read=setup.read)
    written = result.steps[0].written
    assert written is not None
    assert written.name == "Show Name - S01E01 [remux].mkv"
    assert store.is_finished(stamp(written).content_hash, planned.options_key)


class Killed(BaseException):
    """Stands in for the app dying between two steps of a remux."""


def stop_at(name: str) -> Any:
    def checkpoint(step: str) -> None:
        if step == name:
            raise Killed

    return checkpoint


def test_resume_finishes_a_remux_stopped_after_the_original_moved(setup: Any, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    planned = preview([setup.item], setup.profile, setup.stages)
    job = create_job(store, planned, setup.profile, setup.stages)
    step = store.load(job).steps[0]
    mux = setup.stages[1]
    store.set_state(job, step.position, StepState.RUNNING)
    with pytest.raises(Killed):
        apply_mux(step.plan.plan, mux.mkvmerge, mux.programs, recycle=mux.recycle, checkpoint=stop_at("rename"))
    assert not setup.ep.video.exists()  # the original is in the bin, the checked new file under its partial name
    result = run_job(store, job, setup.stages, read=setup.read)
    assert [r.state for r in result.steps] == [StepState.DONE]
    detail = result.steps[0].detail
    assert isinstance(detail, MuxResult)
    assert detail.resumed
    assert store.is_finished(stamp(setup.ep.video).content_hash, planned.options_key)


def test_resume_touches_nothing_when_the_file_changed_by_hand(setup: Any, tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = create_job(store, preview([setup.item], setup.profile, setup.stages), setup.profile, setup.stages)
    step = store.load(job).steps[0]
    store.set_state(job, step.position, StepState.RUNNING)
    setup.ep.video.write_bytes(b"edited by hand")
    result = run_job(store, job, setup.stages, read=setup.read)
    assert [r.state for r in result.steps] == [StepState.STALE]
    assert setup.ep.video.read_bytes() == b"edited by hand"
    assert setup.ep.subtitle.exists()
    assert list((tmp_path / "bin").iterdir()) == []
