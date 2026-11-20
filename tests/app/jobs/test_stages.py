from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.app.jobs import stages
from showrunner.app.jobs.stages import MetadataStage, PlanState, StagePlan, TracksStage
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.track import AudioProperties, Track, TrackKind
from showrunner.stages.metadata import ApplyResult, HeaderChange, MetadataPlan
from showrunner.stages.tracks import KindTest, TrackMatch, TracksOptions
from showrunner.tools.mkvtoolnix.propedit import Property
from showrunner.tools.probe import Programs

TITLE = HeaderChange(Property.TITLE, "", "Movie")
NAME = HeaderChange(Property.NAME, "", "English", 1)
PLAN = StagePlan("metadata", PlanState.CHANGES, MetadataPlan(Path("Movie.mkv"), (TITLE, NAME)), writes=True)


def test_metadata_reports_changes_the_file_does_not_show(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def apply_metadata(plan: MetadataPlan, mkvpropedit: Path, programs: Programs, **kwargs: object) -> ApplyResult:
        calls.append((plan, mkvpropedit))
        return ApplyResult((TITLE,), (NAME,))

    monkeypatch.setattr(stages, "apply_metadata", apply_metadata)
    result = MetadataStage(Path("mkvpropedit"), Programs()).apply(PLAN, None)
    assert calls == [(PLAN.plan, Path("mkvpropedit"))]
    assert not result.ok
    assert result.message == "missed: 1/2"  # worded by the views
    assert result.detail == ApplyResult((TITLE,), (NAME,))


def test_metadata_passes_the_program_error_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stages, "apply_metadata", lambda *a, **k: ApplyResult((), (TITLE, NAME), "exit code 2"))
    assert MetadataStage(Path("mkvpropedit"), Programs()).apply(PLAN, None).message == "exit code 2"


def test_track_plans_are_never_applied() -> None:
    with pytest.raises(NotImplementedError):
        TracksStage().apply(StagePlan("tracks", PlanState.CHANGES), None)


def test_an_order_alone_is_a_change_of_the_track_plan() -> None:
    tracks = (
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC"),
        Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), audio=AudioProperties(6)),
        Track(2, TrackKind.AUDIO, "A_AC3", Language("tur"), audio=AudioProperties(6)),
    )
    item = MediaItem(Movie("Movie Title"), MediaFile(Path("Movie Title.mkv"), "matroska", tracks=tracks))
    order = [TrackMatch(kind=KindTest.AUDIO, languages=["tr"])]
    plan = TracksStage().plan(item, Profile("p", {"tracks": TracksOptions(order=order)}))
    assert (plan.state, plan.needs_remux) == (PlanState.CHANGES, True)
    assert TracksStage().plan(item, Profile("p", {"tracks": TracksOptions()})).state is PlanState.UNCHANGED
