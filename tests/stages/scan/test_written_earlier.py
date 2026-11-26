"""Files an earlier run wrote beside the video, read back by a real scan: they pair next to their original, which stays
the source of the work, and the plan reads them as written earlier."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from showrunner.core.language import Language
from showrunner.core.media import MediaItem
from showrunner.core.track import SubtitleProperties, Track, TrackKind
from showrunner.stages.scan import ScanOptions, scan
from showrunner.stages.subtitles import Output, RuleSetUse, Source, SubtitlesOptions, Translate, Wanted, plan_subtitles
from showrunner.stages.tracks import TracksOptions
from showrunner.tools.cleanit import RuleDef, RuleSet

SETS = {"Lyrics": RuleSet("Lyrics", (RuleDef(name="rule", patterns=("x",)),))}
ENGLISH = Track(0, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties())


def scanned(make: Callable[..., Path], tmp_path: Path, result: str, size: int) -> MediaItem:
    make("Show Name - S01E01.mkv")
    make("Show Name - S01E01.tr.srt", b"x" * 10)
    make(f"Show Name - S01E01{result}.tr.srt", b"x" * size)
    found = scan([tmp_path], ScanOptions(detect_untagged_languages=False))
    assert found.alternatives == ()
    (item,) = found.items
    return replace(item, file=replace(item.file, tracks=(ENGLISH,)))


@pytest.mark.parametrize("size", [1, 100])
def test_a_cleaned_file_reads_as_written_earlier_after_a_real_scan(
    make: Callable[..., Path], tmp_path: Path, size: int
) -> None:
    item = scanned(make, tmp_path, "_cleaned", size)
    options = SubtitlesOptions(cleanup={"Lyrics": RuleSetUse.USED}, output=Output.NEW_FILE)
    plan = plan_subtitles(item, options, TracksOptions(), rule_sets=SETS)
    assert (plan.finished, plan.cannot) == ((), ())
    (earlier,) = plan.written_earlier
    assert (earlier.paired.path.name, earlier.target.name) == (  # type: ignore[union-attr]
        "Show Name - S01E01.tr.srt",
        "Show Name - S01E01_cleaned.tr.srt",
    )


@pytest.mark.parametrize("size", [1, 100])
def test_an_ai_file_reads_as_written_earlier_and_the_original_stays_the_source(
    make: Callable[..., Path], tmp_path: Path, size: int
) -> None:
    item = scanned(make, tmp_path, "_ai", size)
    options = SubtitlesOptions(
        languages={"tr": Wanted.WANTED},
        translate=Translate.ALWAYS,
        output=Output.REPLACE,
        cleanup={"Lyrics": RuleSetUse.USED},
    )
    plan = plan_subtitles(item, options, TracksOptions(), rule_sets=SETS)
    assert [(f.source, f.paired.path.name) for f in plan.finished] == [  # type: ignore[union-attr]
        (Source.PAIRED, "Show Name - S01E01.tr.srt")
    ]
    (earlier,) = plan.written_earlier
    assert (earlier.source, earlier.target.name) == (Source.TRANSLATION, "Show Name - S01E01_ai.tr.srt")  # type: ignore[union-attr]
