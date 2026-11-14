"""Real programs on a tiny file made in `tmp_path`; skipped when ffmpeg or MKVToolNix is missing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaItem
from showrunner.core.naming import NamingOptions
from showrunner.stages.metadata import MetadataOptions, MetadataPlan, apply_metadata, plan_metadata
from showrunner.stages.tracks import FlagShape, KindTest, TrackMatch, TrackRule, TracksOptions
from showrunner.tools.probe import Programs, probe


def find(name: str) -> Path | None:
    if found := shutil.which(name):
        return Path(found)
    folder = Path(os.environ.get("PROGRAMFILES", "")) / "MKVToolNix"
    return next(iter(folder.glob(f"{name}*")), None) if name.startswith("mkv") else None


FFMPEG, MKVMERGE, MKVPROPEDIT = find("ffmpeg"), find("mkvmerge"), find("mkvpropedit")

pytestmark = pytest.mark.skipif(not (FFMPEG and MKVMERGE and MKVPROPEDIT), reason="ffmpeg and MKVToolNix are needed")


def run(*args: str | Path) -> None:
    subprocess.run([str(a) for a in args], check=True, capture_output=True)


@pytest.fixture
def episode(tmp_path: Path) -> MediaItem:
    """Video, two audio tracks without a language, and an English subtitle track named like an SDH track."""
    source = tmp_path / "source.mkv"
    run(
        FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=1",
        "-f", "lavfi", "-i", "sine=d=1", "-f", "lavfi", "-i", "sine=f=880:d=1",
        "-map", "0", "-map", "1", "-map", "2", "-c:v", "mpeg4", "-c:a", "aac", source,
    )  # fmt: skip
    subtitles = tmp_path / "subtitles.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:00,900\nHello\n", encoding="utf-8")
    path = tmp_path / "Show Name - S01E01.mkv"
    run(
        MKVMERGE, "-o", path, "--title", "Old Title",
        "--track-name", "0:Original video", "--default-track-flag", "1:0", "--default-track-flag", "2:1",
        source,
        "--language", "0:eng", "--track-name", "0:English SDH", subtitles,
    )  # fmt: skip
    media = probe(path, Programs(mkvmerge=MKVMERGE))
    assert [t.id for t in media.tracks] == [0, 1, 2, 3]
    return MediaItem(Episode("Show Name", 1, 1), media)


def test_a_plan_is_applied_to_a_real_file_and_found_there_afterwards(episode: MediaItem) -> None:
    tracks = TracksOptions(
        enabled=True,
        rules=[TrackRule(match=TrackMatch(kind=KindTest.AUDIO), default=FlagShape.FIRST)],
    )
    options = MetadataOptions(untagged_language="pt-BR")
    plan = plan_metadata(episode, options, NamingOptions(), tracks, source="WEB-DL")
    assert isinstance(plan, MetadataPlan)
    assert not plan.needs_remux
    assert len(plan.changes) == 10  # title, four names, two languages, two defaults, the implied flag

    result = apply_metadata(plan, MKVPROPEDIT, Programs(mkvmerge=MKVMERGE))
    assert result.ok, result
    assert result.landed == plan.changes

    after = probe(episode.file.path, Programs(mkvmerge=MKVMERGE))
    _, first, second, subtitle = after.tracks
    assert after.title == "Show Name - S01E01"
    assert [t.name for t in after.tracks] == [
        "Show Name - S01E01 (480p WEB-DL)",
        "Show Name - S01E01 (AAC 1.0)",
        "Show Name - S01E01 (AAC 1.0)",
        "Show Name - S01E01",
    ]
    # Both language elements are written; the probe reads the IETF one, so the legacy one is read raw.
    legacy = subprocess.run([str(MKVMERGE), "-J", str(episode.file.path)], check=True, capture_output=True, text=True)
    properties = [t["properties"] for t in json.loads(legacy.stdout)["tracks"]]
    assert [(p["language"], p["language_ietf"]) for p in properties[1:3]] == [("por", "pt-BR")] * 2
    assert (first.language, second.language) == (Language.parse("pt-BR"),) * 2
    assert (subtitle.language, subtitle.flags.hearing_impaired) == (Language.parse("eng"), True)
    # The rule moves the default from the second audio track to the first.
    assert (first.flags.default, second.flags.default) == (True, False)
