from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from showrunner.core.language import Language
from showrunner.core.media import MediaFile
from showrunner.core.track import TrackFlags
from showrunner.stages.metadata import HeaderChange, MetadataPlan, apply_metadata
from showrunner.stages.metadata import apply as apply_module
from showrunner.tools.mkvtoolnix import propedit
from showrunner.tools.probe import ProbeError, Programs
from showrunner.tools.process import ProcessCancelledError, RunResult

PATH = Path("Show Name - S01E01.mkv")
TOOL = Path("mkvpropedit.exe")
PROGRAMS = Programs(mkvmerge=Path("mkvmerge.exe"))

TITLE = HeaderChange(propedit.Property.TITLE, "Old", "New")
NAME = HeaderChange(propedit.Property.NAME, "", "Named", 1)
LANGUAGE = HeaderChange(propedit.Property.LANGUAGE, "", "tr", 1)
FORCED = HeaderChange(propedit.Property.FLAG_FORCED, False, True, 2)


@pytest.fixture
def file(b: SimpleNamespace) -> MediaFile:
    """The file as the plan found it."""
    return b.item(b.video(0), b.audio(1, language=None), b.subtitle(2), title="Old").file


def edited(file: MediaFile) -> MediaFile:
    """The file as it reads when every change of the sample plan landed."""
    audio = replace(file.tracks[1], name="Named", language=Language.parse("tr"))
    subtitle = replace(file.tracks[2], flags=TrackFlags(forced=True))
    return replace(file, title="New", tracks=(file.tracks[0], audio, subtitle))


class Fake:
    """Stands in for mkvpropedit and for the second read of the file."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, after: MediaFile | Exception, run: RunResult | None = None):
        self.after = after
        self.run_result = run or RunResult((), 0, "", "")
        self.runs: list[tuple[str, ...]] = []
        self.reads = 0
        monkeypatch.setattr(propedit, "run", self.run)
        monkeypatch.setattr(apply_module, "probe", self.probe)

    def run(self, args, **_) -> RunResult:
        self.runs.append(tuple(str(a) for a in args))
        return self.run_result

    def probe(self, path, programs, **_) -> MediaFile:
        self.reads += 1
        if isinstance(self.after, Exception):
            raise self.after
        return self.after


def plan(*changes: HeaderChange, needs_remux: bool = False) -> MetadataPlan:
    return MetadataPlan(PATH, changes, needs_remux)


def test_every_change_that_landed_is_confirmed(monkeypatch: pytest.MonkeyPatch, file: MediaFile) -> None:
    fake = Fake(monkeypatch, edited(file))
    result = apply_metadata(plan(TITLE, NAME, LANGUAGE, FORCED), TOOL, PROGRAMS)
    assert result.ok
    assert result.landed == (TITLE, NAME, LANGUAGE, FORCED)
    assert fake.runs == [
        (
            str(TOOL),
            str(PATH),
            "--edit",
            "info",
            "--set",
            "title=New",
            "--edit",
            "track:2",
            "--set",
            "name=Named",
            "--set",
            "language=tur",
            "--set",
            "language-ietf=tr",
            "--edit",
            "track:3",
            "--set",
            "flag-forced=1",
        )
    ]


def test_a_plan_without_changes_runs_and_reads_nothing(monkeypatch: pytest.MonkeyPatch, file: MediaFile) -> None:
    fake = Fake(monkeypatch, file)
    assert apply_metadata(plan(), TOOL, PROGRAMS).ok
    assert (fake.runs, fake.reads) == ([], 0)


def test_a_plan_that_a_remux_carries_out_runs_nothing(monkeypatch: pytest.MonkeyPatch, file: MediaFile) -> None:
    fake = Fake(monkeypatch, file)
    assert apply_metadata(plan(TITLE, needs_remux=True), TOOL, PROGRAMS).ok
    assert (fake.runs, fake.reads) == ([], 0)


def test_a_change_the_file_does_not_show_is_reported(monkeypatch: pytest.MonkeyPatch, file: MediaFile) -> None:
    after = replace(edited(file), title="Old")
    Fake(monkeypatch, after)
    result = apply_metadata(plan(TITLE, NAME, FORCED), TOOL, PROGRAMS)
    assert not result.ok
    assert (result.landed, result.missed, result.error) == ((NAME, FORCED), (TITLE,), "")


def test_a_track_that_is_gone_after_the_edit_counts_as_missed(monkeypatch: pytest.MonkeyPatch, file: MediaFile) -> None:
    Fake(monkeypatch, replace(edited(file), tracks=edited(file).tracks[:2]))
    result = apply_metadata(plan(NAME, FORCED), TOOL, PROGRAMS)
    assert (result.landed, result.missed) == ((NAME,), (FORCED,))


def test_a_failed_run_is_reported_and_what_did_land_is_still_found(
    monkeypatch: pytest.MonkeyPatch, file: MediaFile
) -> None:
    failed = RunResult((), 2, "Error: cannot write the file", "")
    Fake(monkeypatch, replace(file, title="New"), failed)
    result = apply_metadata(plan(TITLE, NAME), TOOL, PROGRAMS)
    assert not result.ok
    assert (result.landed, result.missed) == ((TITLE,), (NAME,))
    assert result.error == "Error: cannot write the file"


def test_a_file_that_cannot_be_read_again_leaves_every_change_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    Fake(monkeypatch, ProbeError("could not be read"))
    result = apply_metadata(plan(TITLE, NAME), TOOL, PROGRAMS)
    assert (result.landed, result.missed, result.error) == ((), (TITLE, NAME), "could not be read")


def test_a_file_read_without_mkvmerge_cannot_be_checked(monkeypatch: pytest.MonkeyPatch, file: MediaFile) -> None:
    Fake(monkeypatch, replace(edited(file), ids_from_mkvmerge=False))
    result = apply_metadata(plan(TITLE), TOOL, PROGRAMS)
    assert result.missed == (TITLE,)
    assert "without mkvmerge" in result.error


def test_cancelling_is_not_swallowed(monkeypatch: pytest.MonkeyPatch, file: MediaFile) -> None:
    Fake(monkeypatch, ProcessCancelledError("cancelled", ["x"]))
    with pytest.raises(ProcessCancelledError):
        apply_metadata(plan(TITLE), TOOL, PROGRAMS)
