from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.app.jobs import stages
from showrunner.app.jobs.stages import MetadataStage, PlanState, StagePlan, TracksStage
from showrunner.stages.metadata import ApplyResult, HeaderChange, MetadataPlan
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
    assert result.message == "1 of 2 changes not found after the edit"
    assert result.detail == ApplyResult((TITLE,), (NAME,))


def test_metadata_passes_the_program_error_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stages, "apply_metadata", lambda *a, **k: ApplyResult((), (TITLE, NAME), "exit code 2"))
    assert MetadataStage(Path("mkvpropedit"), Programs()).apply(PLAN, None).message == "exit code 2"


def test_track_plans_are_never_applied() -> None:
    with pytest.raises(NotImplementedError):
        TracksStage().apply(StagePlan("tracks", PlanState.CHANGES), None)
