from __future__ import annotations

from showrunner.app.library.library import Library
from showrunner.ui.sheet.format import duration_text, size_text, track_summary


def test_the_codec_line_depends_on_the_kind_of_track(sample_library: Library) -> None:
    video, audio, subtitle = sample_library.items[0].file.tracks
    assert track_summary(video) == "HEVC · 1080p · 10-bit · 23.976 fps"
    assert track_summary(audio) == "AC-3 · 5.1"
    assert track_summary(subtitle) == "SubRip · text"


def test_sizes_and_durations_read_short() -> None:
    assert size_text(214_000) == "214 KB"
    assert size_text(6_840_000_000) == "6.84 GB"
    assert size_text(12) == "12 B"
    assert duration_text(49 * 60 + 12) == "49:12"
    assert duration_text(3600 + 61) == "1:01:01"
