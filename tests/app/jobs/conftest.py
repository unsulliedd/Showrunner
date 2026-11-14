from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from showrunner.app.jobs.stages import PlanState, StagePlan, StepResult
from showrunner.app.jobs.store import JobStore
from showrunner.app.profiles import registered  # noqa: F401
from showrunner.app.profiles.profile import Profile
from showrunner.core.media import MediaFile, MediaItem, Movie


class Killed(BaseException):
    """Stands in for the process dying: no `except Exception` catches it."""


def read(path: Path) -> MediaFile:
    """The fake probe: the file's text becomes its title, so a plan sees what was written."""
    return MediaFile(path, "matroska", title=path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class FakeStage:
    """Appends `+edited` to a file whose text does not end with it. A text containing `fail` makes the write fail,
    one containing `refuse` is refused."""

    id: ClassVar[str] = "metadata"
    remuxes: ClassVar[bool] = False
    crash_on: str = ""  # file name whose apply is killed
    crash_after_write: bool = False
    applied: list[str] = field(default_factory=list, repr=False, compare=False)

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        text = item.file.title
        if "refuse" in text:
            return StagePlan(self.id, PlanState.REFUSED, "refused")
        if text.endswith("+edited"):
            return StagePlan(self.id, PlanState.UNCHANGED, (str(item.file.path), text))
        return StagePlan(self.id, PlanState.CHANGES, (str(item.file.path), text), writes=True)

    def apply(self, plan: StagePlan, cancel: threading.Event | None) -> StepResult:
        path = Path(plan.plan[0])  # type: ignore[index]
        if path.name == self.crash_on and not self.crash_after_write:
            raise Killed
        text = path.read_text(encoding="utf-8")
        if "fail" in text:
            raise OSError("disk full")
        path.write_text(text + "+edited", encoding="utf-8")
        if path.name == self.crash_on:
            raise Killed
        self.applied.append(path.name)
        return StepResult(True)


@dataclass(frozen=True)
class SecondStage(FakeStage):
    """A second stage that writes, under the id of a stage that is off by default."""

    id: ClassVar[str] = "tracks"


@pytest.fixture
def files(tmp_path: Path) -> SimpleNamespace:
    def item(name: str, text: str = "plain") -> MediaItem:
        path = tmp_path / "lib" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return MediaItem(Movie(path.stem), read(path))

    return SimpleNamespace(item=item, read=read, Killed=Killed, FakeStage=FakeStage, SecondStage=SecondStage)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "data" / "jobs.sqlite3")


@pytest.fixture
def profile() -> Profile:
    return Profile.defaults("Test")
