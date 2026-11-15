"""Leaving a group of planned changes or a file out of a run."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from showrunner.app.jobs.blocked import blocked_stages
from showrunner.app.jobs.groups import ChangeGroup, without
from showrunner.app.jobs.preview import FileOutcome, preview
from showrunner.app.jobs.run import StalePreviewError, create_job, run_job
from showrunner.app.jobs.stages import (
    RECHECK,
    MetadataStage,
    PlanState,
    Resumed,
    StagePlan,
    StepResult,
    TracksStage,
)
from showrunner.app.jobs.store import JobStore, StepState
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.track import AudioProperties, Track, TrackFlags, TrackKind, VideoProperties
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.tracks import FlagShape, KindTest, TrackMatch, TrackRule, TracksOptions, Verdict
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.tools.probe import Programs

METADATA = MetadataStage(Path("mkvpropedit"), Programs())
DROP_FRENCH = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["fre"]), verdict=Verdict.DROP)
ENGLISH_DEFAULT = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["en"]), default=FlagShape.FIRST)


@dataclass(frozen=True)
class Remux:
    """Stands in for Mux: it carries out any track plan that needs a new file."""

    id: ClassVar[str] = "mux"
    remuxes: ClassVar[bool] = True

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        tracks = TracksStage().plan(item, profile)
        if not tracks.needs_remux:
            return StagePlan(self.id, PlanState.UNCHANGED)
        return StagePlan(self.id, PlanState.CHANGES, writes=True, needs_remux=True)

    def apply(self, plan: StagePlan, cancel: threading.Event | None, progress: object = None) -> StepResult:
        raise AssertionError("not applied here")

    def resume(self, plan: StagePlan, before: object, cancel: threading.Event | None) -> Resumed:
        return RECHECK


STAGES = (TracksStage(), Remux(), METADATA)


def movie(tmp_path: Path, name: str = "Movie Title (2016).mkv") -> MediaItem:
    path = tmp_path / name
    path.write_bytes(b"matroska")
    tracks = (
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080, 23.976)),
        Track(1, TrackKind.AUDIO, "A_AC3", Language("fra"), flags=TrackFlags(default=True), audio=AudioProperties(6)),
        Track(2, TrackKind.AUDIO, "A_AC3", Language("eng"), audio=AudioProperties(6)),
    )
    return MediaItem(Movie("Movie Title", 2016), MediaFile(path, "matroska", tracks=tracks))


def with_rules(profile: Profile, *rules: TrackRule) -> Profile:
    return profile.with_options("tracks", TracksOptions(rules=list(rules)))


def props(plan: StagePlan | None) -> set[Property]:
    assert plan is not None
    assert isinstance(plan.plan, MetadataPlan)
    return {change.prop for change in plan.plan.changes}


def test_leaving_names_out_keeps_the_rules_flags_and_drops_titles_and_names(tmp_path: Path, profile: Profile) -> None:
    flags = with_rules(profile, ENGLISH_DEFAULT)
    (full,) = preview([movie(tmp_path)], flags, STAGES).files
    assert props(full.plan_for("metadata")) == {Property.TITLE, Property.NAME, Property.FLAG_DEFAULT}
    (run,) = preview([movie(tmp_path)], flags, STAGES, left_out={ChangeGroup.NAMES}).files
    # Metadata still runs: it is the stage that writes the default flag the rules moved.
    assert props(run.plan_for("metadata")) == {Property.FLAG_DEFAULT}
    assert run.outcome is FileOutcome.CHANGES


def test_leaving_tracks_out_means_no_new_file_and_the_names_go_in_place(tmp_path: Path, profile: Profile) -> None:
    drops = with_rules(profile, DROP_FRENCH, ENGLISH_DEFAULT)
    (full,) = preview([movie(tmp_path)], drops, STAGES).files
    assert [p.stage for p in full.writes] == ["mux"]
    (run,) = preview([movie(tmp_path)], drops, STAGES, left_out={ChangeGroup.TRACKS}).files
    assert run.plan_for("tracks").state is PlanState.UNCHANGED  # type: ignore[union-attr]
    assert run.plan_for("mux").state is PlanState.UNCHANGED  # type: ignore[union-attr]
    assert [p.stage for p in run.writes] == ["metadata"]
    assert Property.FLAG_DEFAULT not in props(run.plan_for("metadata"))


def test_leaving_every_group_out_changes_nothing(tmp_path: Path, profile: Profile) -> None:
    drops = with_rules(profile, DROP_FRENCH)
    (run,) = preview([movie(tmp_path)], drops, STAGES, left_out=set(ChangeGroup)).files
    assert run.outcome is FileOutcome.UNCHANGED


def test_the_preview_profile_asks_nothing_of_a_left_out_group(profile: Profile) -> None:
    drops = with_rules(profile, DROP_FRENCH)
    planned = preview([], drops, STAGES, left_out={ChangeGroup.TRACKS, ChangeGroup.NAMES}).profile
    assert planned.for_stage("tracks").rules == []
    assert planned.for_stage("naming").title_template == ""
    assert planned == without(without(drops, ChangeGroup.TRACKS), ChangeGroup.NAMES)


def test_a_left_out_file_gets_no_step_and_needs_no_new_preview(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stage = files.FakeStage()
    a, b = files.item("a.mkv"), files.item("b.mkv")
    made = preview([a, b], profile, (stage,))
    job = create_job(store, made, profile, (stage,), left_out_files={a.file.path})
    assert [s.path.name for s in store.load(job).steps] == ["b.mkv"]


def test_a_preview_made_for_other_groups_is_refused(files: SimpleNamespace, store: JobStore, profile: Profile) -> None:
    stage = files.FakeStage()
    made = preview([files.item("a.mkv")], profile, (stage,), left_out={ChangeGroup.NAMES})
    with pytest.raises(StalePreviewError):
        create_job(store, made, profile, (stage,))
    assert create_job(store, made, profile, (stage,), left_out={ChangeGroup.NAMES})


@dataclass(frozen=True)
class FlagStage:
    """Plans a change while a rule is on, and carries the title template in its plan, so that a re-plan with other
    naming options comes out different."""

    id: ClassVar[str] = "metadata"
    remuxes: ClassVar[bool] = False

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        if not profile.for_stage("tracks").rules:
            return StagePlan(self.id, PlanState.UNCHANGED)
        return StagePlan(self.id, PlanState.CHANGES, profile.for_stage("naming").title_template, writes=True)

    def apply(self, plan: StagePlan, cancel: threading.Event | None, progress: object = None) -> StepResult:
        return StepResult(True)

    def resume(self, plan: StagePlan, before: object, cancel: threading.Event | None) -> Resumed:
        return RECHECK


def test_a_resumed_job_plans_again_with_the_groups_it_left_out(
    files: SimpleNamespace, store: JobStore, profile: Profile
) -> None:
    stages = (FlagStage(),)
    flags = with_rules(profile, ENGLISH_DEFAULT)
    made = preview([files.item("a.mkv")], flags, stages, left_out={ChangeGroup.NAMES})
    job = create_job(store, made, flags, stages, left_out={ChangeGroup.NAMES})
    assert store.load(job).profile.for_stage("naming").title_template == ""
    # The app stopped during the step. Planned again with the full options, the plan would hold a title and the
    # step would count as stale; with the stored ones it equals the plan and runs again.
    store.set_state(job, 0, StepState.RUNNING)
    result = run_job(store, job, stages, read=files.read)
    assert [r.state for r in result.steps] == [StepState.DONE]


def test_a_problem_in_a_left_out_group_blocks_nothing(tmp_path: Path, profile: Profile) -> None:
    broken = with_rules(profile, ENGLISH_DEFAULT)
    broken = broken.with_options("naming", replace(broken.for_stage("naming"), audio_track_template="{nope}"))
    blocked = set(blocked_stages(broken))
    assert blocked == {"metadata"}
    (run,) = preview([movie(tmp_path)], broken, STAGES, blocked=blocked, left_out={ChangeGroup.NAMES}).files
    # Metadata is planned after all, as the writer of the default flag the rules move.
    assert run.outcome is FileOutcome.CHANGES
    assert props(run.plan_for("metadata")) == {Property.FLAG_DEFAULT}
