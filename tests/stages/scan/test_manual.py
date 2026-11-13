from __future__ import annotations

from pathlib import Path

from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie, SubtitleFile
from showrunner.stages.scan import attach, detach, move_subtitle


def item(name: str, *subtitles: SubtitleFile) -> MediaItem:
    return MediaItem(Movie(name), MediaFile(Path(f"{name}.mkv"), "mkv"), subtitles)


EN = SubtitleFile(Path("a.en.srt"), Language("eng"))
TR = SubtitleFile(Path("a.tr.srt"), Language("tur"))


def test_attach_adds_and_leaves_the_original_untouched() -> None:
    original = item("a", EN)
    attached = attach(original, TR)
    assert attached.subtitles == (EN, TR)
    assert original.subtitles == (EN,)


def test_attach_replaces_the_same_file() -> None:
    corrected = SubtitleFile(EN.path, Language("tur"), forced=True)
    assert attach(item("a", EN), corrected).subtitles == (corrected,)


def test_detach_removes_by_path_and_ignores_unknown_files() -> None:
    original = item("a", EN, TR)
    assert detach(original, EN.path).subtitles == (TR,)
    assert detach(original, Path("other.srt")) == original


def test_move_takes_the_file_from_every_other_item() -> None:
    first, second = item("a", EN), item("b")
    moved = move_subtitle([first, second], EN, Path("b.mkv"))
    assert [m.subtitles for m in moved] == [(), (EN,)]
    assert first.subtitles == (EN,)


def test_move_to_nobody_only_detaches() -> None:
    assert [m.subtitles for m in move_subtitle([item("a", EN), item("b")], EN, None)] == [(), ()]
