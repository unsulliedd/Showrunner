"""Finished subtitles written beside the video: their names, the plan's targets and the problems it names, and the
order in which one takes its place."""

from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.core.cue import Cue, read_cues, write_cues
from showrunner.core.language import Language
from showrunner.stages.scan.names import parse_subtitle_name
from showrunner.stages.scan.pairing import name_keys, pair
from showrunner.stages.subtitles import Output, SubtitlesOptions
from showrunner.stages.subtitles.beside import (
    BesideError,
    BesideFailure,
    finish_replace,
    is_result,
    language_name,
    new_file_name,
    partial_path,
    write_beside,
)
from showrunner.stages.subtitles.options import bad_new_file_text, text_problem


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Show.S01E01.tr.srt", "Show.S01E01_cleaned.tr.srt"),
        ("Show.S01E01.tr.forced.srt", "Show.S01E01_cleaned.tr.forced.srt"),
        ("Show.S01E01.eng.sdh.ass", "Show.S01E01_cleaned.eng.sdh.ass"),
        ("Show.S01E01.pt-BR.srt", "Show.S01E01_cleaned.pt-BR.srt"),
        ("Show.S01E01.srt", "Show.S01E01_cleaned.srt"),
    ],
)
def test_the_new_file_text_goes_before_the_language_and_flags(name: str, expected: str) -> None:
    assert new_file_name(name, "_cleaned") == expected
    # A scan reads the new name as it read the old one, and takes the text for part of the name it pairs by.
    old, new = parse_subtitle_name(name), parse_subtitle_name(expected)
    assert (new.language, new.forced, new.sdh) == (old.language, old.forced, old.sdh)
    assert is_result(expected, "_cleaned")
    assert not is_result(name, "_cleaned")


def test_a_new_file_still_pairs_with_its_video() -> None:
    videos = name_keys(["Show.S01E01", "Show.S01E02"])
    subtitles = name_keys([parse_subtitle_name("Show.S01E02_cleaned.tr.srt").base])
    (match,) = pair(videos, subtitles, [1, 1])
    assert match.video == 1


def test_a_subtitle_without_a_file_is_named_by_its_language() -> None:
    assert language_name("Show.S01E01", Language("tur"), "srt") == "Show.S01E01.tr.srt"
    assert language_name("Show.S01E01", Language.parse("pt-BR"), "srt") == "Show.S01E01.pt-BR.srt"
    assert parse_subtitle_name("Show.S01E01.pt-BR.srt").language == Language.parse("pt-BR")
    named = language_name("Show.S01E01", Language("eng"), "srt", forced=True, sdh=True)
    assert named == "Show.S01E01.en.forced.sdh.srt"
    read = parse_subtitle_name(named)
    assert (read.language, read.forced, read.sdh) == (Language("eng"), True, True)


def test_a_result_is_known_whatever_the_case_of_its_text() -> None:
    assert is_result("Show.S01E01_CLEANED.tr.srt", "_cleaned")


@pytest.mark.parametrize("text", ["", "   ", "a/b", "a\\b", "a:b", "tab\there"])
def test_a_new_file_text_that_cannot_name_a_file_is_a_problem(text: str) -> None:
    assert bad_new_file_text(text)
    assert text_problem(SubtitlesOptions(output=Output.NEW_FILE, new_file_text=text))
    # Nothing reads it while the subtitles go into the video or replace their file.
    assert not text_problem(SubtitlesOptions(output=Output.REPLACE, new_file_text=text))


def test_a_good_new_file_text_is_none() -> None:
    assert not bad_new_file_text("_cleaned")
    assert not bad_new_file_text(".clean")
    assert not text_problem(SubtitlesOptions(output=Output.NEW_FILE))


# Writing one


def cues(path: Path, *texts: str) -> Path:
    write_cues(path, [Cue(float(n), n + 0.5, text) for n, text in enumerate(texts, 1)])
    return path


class Bin:
    """Stands in for the Recycle Bin: moves the files into a folder, or refuses."""

    def __init__(self, folder: Path, *, refuse: bool = False) -> None:
        self.folder = folder
        self.refuse = refuse
        self.got: list[Path] = []

    def __call__(self, paths: object) -> None:
        if self.refuse:
            raise OSError("no Recycle Bin")
        self.folder.mkdir(exist_ok=True)
        for path in paths:  # type: ignore[attr-defined]
            path.rename(self.folder / path.name)
            self.got.append(path)


def test_a_new_file_is_written_and_the_original_stays(tmp_path: Path) -> None:
    result, original = cues(tmp_path / "result.srt", "CLEAN"), cues(tmp_path / "Show.tr.srt", "dirty")
    target = tmp_path / "Show_cleaned.tr.srt"
    write_beside(result, target, None, replaces=False, recycle=Bin(tmp_path / "bin", refuse=True))
    assert [c.text for c in read_cues(target)] == ["CLEAN"]
    assert [c.text for c in read_cues(original)] == ["dirty"]
    assert not partial_path(target).exists()


def test_replacing_recycles_the_original_after_the_check(tmp_path: Path) -> None:
    result, original = cues(tmp_path / "result.srt", "CLEAN"), cues(tmp_path / "Show.tr.srt", "dirty")
    recycle = Bin(tmp_path / "bin")
    write_beside(result, original, None, replaces=True, recycle=recycle)
    assert [c.text for c in read_cues(original)] == ["CLEAN"]
    assert [c.text for c in read_cues(tmp_path / "bin" / "Show.tr.srt")] == ["dirty"]


def test_a_failed_check_leaves_the_original_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, original = cues(tmp_path / "result.srt", "CLEAN"), cues(tmp_path / "Show.tr.srt", "dirty")
    recycle = Bin(tmp_path / "bin")

    def broken_copy(source: Path, destination: Path) -> None:
        cues(destination, "something else")

    monkeypatch.setattr("showrunner.stages.subtitles.beside.shutil.copyfile", broken_copy)
    with pytest.raises(BesideError) as raised:
        write_beside(result, original, None, replaces=True, recycle=recycle)
    assert raised.value.failure is BesideFailure.CHECK
    assert recycle.got == []
    assert [c.text for c in read_cues(original)] == ["dirty"]
    assert not partial_path(original).exists()


def test_a_refused_recycle_leaves_the_original_untouched(tmp_path: Path) -> None:
    result, original = cues(tmp_path / "result.srt", "CLEAN"), cues(tmp_path / "Show.tr.srt", "dirty")
    with pytest.raises(BesideError) as raised:
        write_beside(result, original, None, replaces=True, recycle=Bin(tmp_path / "bin", refuse=True))
    assert raised.value.failure is BesideFailure.RECYCLE
    assert [c.text for c in read_cues(original)] == ["dirty"]
    assert not partial_path(original).exists()


def test_a_file_in_the_way_is_never_overwritten(tmp_path: Path) -> None:
    result, there = cues(tmp_path / "result.srt", "CLEAN"), cues(tmp_path / "Show_cleaned.tr.srt", "mine")
    with pytest.raises(BesideError) as raised:
        write_beside(result, there, None, replaces=False)
    assert raised.value.failure is BesideFailure.EXISTS
    assert [c.text for c in read_cues(there)] == ["mine"]


def test_a_file_that_already_reads_as_the_result_is_left_as_it_is(tmp_path: Path) -> None:
    result, there = cues(tmp_path / "result.srt", "CLEAN"), cues(tmp_path / "Show.tr.srt", "CLEAN")
    recycle = Bin(tmp_path / "bin")
    write_beside(result, there, None, replaces=True, recycle=recycle)
    write_beside(result, there, None, replaces=False, recycle=recycle)
    assert recycle.got == []


def test_a_stop_after_the_recycle_is_finished_by_the_rename(tmp_path: Path) -> None:
    original = tmp_path / "Show.tr.srt"
    assert not finish_replace(cues(original, "dirty"))
    cues(partial_path(original), "CLEAN")
    original.unlink()  # gone to the Recycle Bin
    assert finish_replace(original)
    assert [c.text for c in read_cues(original)] == ["CLEAN"]
    assert not partial_path(original).exists()
