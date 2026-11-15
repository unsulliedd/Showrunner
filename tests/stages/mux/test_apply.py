"""Real mkvmerge on a small file in `tmp_path`; skipped without ffmpeg and MKVToolNix. The Recycle Bin is a folder
of the test: the shell is never asked."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaItem, SubtitleFile
from showrunner.core.naming import NamingOptions
from showrunner.stages.metadata import MetadataOptions
from showrunner.stages.mux import Failure, MuxOptions, MuxPlan, Original, apply_mux, check, plan_mux, resume_mux
from showrunner.stages.mux import apply as module
from showrunner.stages.tracks import KindTest, PairedFile, TrackMatch, TrackRule, TracksOptions, Verdict
from showrunner.tools.probe import Programs, probe
from showrunner.tools.process import ProcessCancelledError

DROP_FRENCH = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["fre"]), verdict=Verdict.DROP)
TURKISH_LINE = "Güzel şehir"


class Killed(BaseException):
    """Stands in for the process dying between two steps: no `except Exception` catches it."""


class Bin:
    """A folder standing in for the Recycle Bin."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir()
        self.fail = False

    def __call__(self, paths: Sequence[Path]) -> None:
        if self.fail:
            raise OSError("the Recycle Bin is not available")
        for path in paths:
            path.rename(self.folder / path.name)

    def names(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir())


@pytest.fixture
def bin_(tmp_path: Path) -> Bin:
    return Bin(tmp_path / "bin")


def make_plan(episode: Any, **mux: Any) -> tuple[MuxPlan, Programs]:
    programs = Programs(mkvmerge=episode.mkvmerge)
    subtitle = SubtitleFile(episode.subtitle, Language("tur"))
    item = MediaItem(Episode("Show Name", 1, 1), probe(episode.video, programs), (subtitle,))
    naming = replace(NamingOptions(), title_template="{show} S{season:02}E{episode:02}")
    result = plan_mux(
        item,
        MuxOptions(**mux),
        TracksOptions(rules=[DROP_FRENCH], add_paired=[PairedFile.of(subtitle)]),
        MetadataOptions(),
        naming,
    )
    assert isinstance(result, MuxPlan)
    return result, programs


def videos(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.suffix == ".mkv")


def test_a_remux_writes_checks_and_recycles_the_original(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode)
    original = real_episode.video.read_bytes()
    seen: list[float] = []
    result = apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_, progress=seen.append)
    assert result.ok, result
    assert result.output == real_episode.video
    assert seen
    assert seen[-1] == 1.0
    assert bin_.names() == ["Show Name - S01E01.mkv", "Show Name - S01E01.tr.srt"]
    assert (bin_.folder / "Show Name - S01E01.mkv").read_bytes() == original
    assert videos(real_episode.video.parent) == ["Show Name - S01E01.mkv"]  # no partial file left
    after = probe(real_episode.video, programs)
    assert [(t.kind.value, t.language) for t in after.tracks] == [
        ("video", None),
        ("audio", Language("eng")),
        ("subtitle", Language("tur")),
    ]
    assert after.title == plan.title
    assert not after.tracks[2].flags.default  # mkvmerge would have made the added subtitle a default track


def test_the_subtitle_text_is_converted_from_its_code_page(real_episode: Any, bin_: Bin, tmp_path: Path) -> None:
    plan, programs = make_plan(real_episode)
    assert apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_).ok
    extract = real_episode.mkvmerge.with_name(real_episode.mkvmerge.name.replace("mkvmerge", "mkvextract"))
    out = tmp_path / "out.srt"
    subprocess.run([extract, real_episode.video, "tracks", f"2:{out}"], check=True, capture_output=True)
    assert TURKISH_LINE in out.read_text(encoding="utf-8-sig")


def test_keep_moves_the_original_into_the_folder_and_numbers_a_second_one(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode, original=Original.KEEP)
    kept = plan.keep_dir
    kept.mkdir()
    (kept / "Show Name - S01E01.mkv").write_bytes(b"an earlier original")
    result = apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_)
    assert result.ok, result
    assert sorted(p.name for p in kept.iterdir()) == [
        "Show Name - S01E01 (2).mkv",
        "Show Name - S01E01.mkv",
        "Show Name - S01E01.tr.srt",
    ]
    assert result.kept[0] == kept / "Show Name - S01E01 (2).mkv"
    assert bin_.names() == []


def test_a_failed_check_removes_the_new_file_and_leaves_the_original(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode)
    original = real_episode.video.read_bytes()
    wrong = replace(plan, duration=(plan.duration or 0) + 30)
    result = apply_mux(wrong, real_episode.mkvmerge, programs, recycle=bin_)
    assert result.failure is Failure.VERIFY
    assert [p.what for p in result.problems] == ["duration"]
    assert real_episode.video.read_bytes() == original
    assert real_episode.subtitle.exists()
    assert videos(real_episode.video.parent) == ["Show Name - S01E01.mkv"]
    assert bin_.names() == []


def test_a_mkvmerge_error_leaves_the_original(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode)
    original = real_episode.video.read_bytes()
    real_episode.subtitle.unlink()
    result = apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_)
    assert result.failure is Failure.MERGE
    assert "could not be opened" in result.detail
    assert real_episode.video.read_bytes() == original
    assert videos(real_episode.video.parent) == ["Show Name - S01E01.mkv"]


def test_cancel_during_the_merge_removes_the_partial_file(
    real_episode: Any, bin_: Bin, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, programs = make_plan(real_episode)
    original = real_episode.video.read_bytes()

    def cancelled(_mkvmerge: Path, spec: Any, **_: Any) -> None:
        spec.output.write_bytes(b"half a file")
        raise ProcessCancelledError("cancelled", ())

    monkeypatch.setattr(module, "merge", cancelled)
    with pytest.raises(ProcessCancelledError):
        apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_)
    assert not plan.partial.exists()
    assert real_episode.video.read_bytes() == original


def test_an_original_that_cannot_be_recycled_stays_and_nothing_changes(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode)
    original = real_episode.video.read_bytes()
    bin_.fail = True
    result = apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_)
    assert result.failure is Failure.DISPOSE
    assert real_episode.video.read_bytes() == original
    assert real_episode.subtitle.exists()
    assert not plan.partial.exists()


def test_a_recycle_that_fails_after_moving_the_original_keeps_the_new_file(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode)

    def moved_then_failed(paths: Sequence[Path]) -> None:
        for path in paths:
            path.rename(bin_.folder / path.name)
        raise OSError("the shell reported a failure")

    result = apply_mux(plan, real_episode.mkvmerge, programs, recycle=moved_then_failed)
    assert result.failure is Failure.DISPOSE
    assert plan.partial.exists()
    finished = resume_mux(plan, programs, source_unchanged=False, recycle=bin_)
    assert finished is not None
    assert finished.ok, finished
    assert videos(real_episode.video.parent) == ["Show Name - S01E01.mkv"]


def test_an_existing_file_under_the_new_name_is_never_replaced(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode, suffix=" [remux]")
    plan.output.write_bytes(b"another file")
    result = apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_)
    assert result.failure is Failure.OUTPUT_EXISTS
    assert plan.output.read_bytes() == b"another file"


def stop_at(name: str) -> Callable[[str], None]:
    def checkpoint(step: str) -> None:
        if step == name:
            raise Killed

    return checkpoint


@pytest.mark.parametrize("gap", ["merge", "verify", "original", "rename", "subtitles"])
@pytest.mark.parametrize("original", [Original.RECYCLE, Original.KEEP])
def test_a_run_stopped_at_any_point_is_finished_by_resume(
    real_episode: Any, bin_: Bin, gap: str, original: Original
) -> None:
    plan, programs = make_plan(real_episode, original=original)
    before = real_episode.video.read_bytes()
    with pytest.raises(Killed):
        apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_, checkpoint=stop_at(gap))
    # Wherever it stopped, the original's bytes are in one known place.
    places = [real_episode.video, bin_.folder / real_episode.video.name, plan.keep_dir / real_episode.video.name]
    assert any(p.exists() and p.read_bytes() == before for p in places)

    unchanged = real_episode.video.exists() and real_episode.video.read_bytes() == before
    result = resume_mux(plan, programs, source_unchanged=unchanged, recycle=bin_)
    if result is None:  # the original was as planned: the step runs again
        assert not plan.partial.exists()
        result = apply_mux(plan, real_episode.mkvmerge, programs, recycle=bin_)
    assert result.ok, result
    assert videos(real_episode.video.parent) == ["Show Name - S01E01.mkv"]
    assert not check(plan, real_episode.video, programs)
    assert not real_episode.subtitle.exists()
    moved = bin_.names() if original is Original.RECYCLE else sorted(p.name for p in plan.keep_dir.iterdir())
    assert moved == ["Show Name - S01E01.mkv", "Show Name - S01E01.tr.srt"]


def test_resume_leaves_files_it_cannot_place(real_episode: Any, bin_: Bin) -> None:
    plan, programs = make_plan(real_episode)
    real_episode.video.write_bytes(b"edited by hand since the preview")
    result = resume_mux(plan, programs, source_unchanged=False, recycle=bin_)
    assert result is not None
    assert result.failure is Failure.STALE
    assert real_episode.video.read_bytes() == b"edited by hand since the preview"
    assert bin_.names() == []
