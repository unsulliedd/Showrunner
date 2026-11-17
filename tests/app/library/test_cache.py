"""The read cache: what was read from each video, served again only while the file and the programs are unchanged."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

import pytest

from showrunner.app.library.cache import FORMAT_VERSION, media_from_json, media_to_json
from showrunner.app.library.service import load_library
from showrunner.core.language import Language
from showrunner.core.media import Attachment, Chapter, ChapterName, MediaFile
from showrunner.core.track import (
    AudioProperties,
    HdrKind,
    ObjectAudio,
    SubtitleProperties,
    Track,
    TrackFlags,
    TrackKind,
    VideoProperties,
)
from showrunner.tools.probe import ProbeError, Programs

PROGRAMS = Programs(Path("mkvmerge"), Path("mkvextract"), Path("ffprobe"))


def rich_file(path: Path) -> MediaFile:
    """Every kind of value a probe gives: each HDR kind and object audio, languages with a region and a script,
    unknown property groups, a chapter with no end and a name with no language."""
    videos = tuple(
        Track(n, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(3840, 2160, 23.976, hdr, 10))
        for n, hdr in enumerate(HdrKind)
    )
    audios = tuple(
        Track(
            len(videos) + n,
            TrackKind.AUDIO,
            "A_TRUEHD",
            Language("por", "BR"),
            "Português 7.1",
            TrackFlags(default=True, original=True),
            audio=AudioProperties(8, 48000, objects),
        )
        for n, objects in enumerate(ObjectAudio)
    )
    others = (
        Track(20, TrackKind.VIDEO, "V_MS/VFW/FOURCC"),
        Track(21, TrackKind.AUDIO, "A_AAC", audio=AudioProperties()),
        Track(
            22,
            TrackKind.SUBTITLE,
            "S_HDMV/PGS",
            Language("zho", script="Hant"),
            "繁體中文",
            TrackFlags(True, True, True, True, True, True),
            subtitle=SubtitleProperties(text_based=False),
        ),
        Track(23, TrackKind.SUBTITLE, "S_TEXT/UTF8", subtitle=SubtitleProperties()),
    )
    return MediaFile(
        path,
        "Matroska",
        duration=2711.488,
        size=4_812_345_678,
        modified_ns=1_731_839_012_345_678_901,
        title="Episode Title",
        tracks=(*videos, *audios, *others),
        chapters=(
            Chapter(0.0, 95.5, (ChapterName(Language("eng"), "Opening"), ChapterName(Language("tur"), "Giriş"))),
            Chapter(95.5, None, (ChapterName(None, "Part 1"),)),
            Chapter(1800.25),
        ),
        attachments=(Attachment(1, "cover.jpg", "image/jpeg", 214_000, "Cover"), Attachment(2, "font.ttf", "", 0)),
        ids_from_mkvmerge=False,
    )


class Counted:
    """A stand-in reader that counts its calls; `fail` names files it cannot read."""

    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.fail: set[str] = set()

    def __call__(self, path: Path, programs: Programs, *, cancel: threading.Event | None) -> MediaFile:
        self.calls.append(path)
        if path.name in self.fail:
            raise ProbeError("broken header")
        return rich_file(path)


@pytest.fixture
def show(make: Callable[..., Path], tmp_path: Path) -> Path:
    make("Show/Show S01E01.mkv")
    make("Show/Show S01E02.mkv")
    return tmp_path / "Show"


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "data" / "read_cache.json"


def names(paths: list[Path]) -> list[str]:
    return [p.name for p in paths]


def test_a_probed_file_survives_the_round_trip_unchanged(tmp_path: Path) -> None:
    file = rich_file(tmp_path / "Show S01E01.mkv")
    stored = json.loads(json.dumps(media_to_json(file)))
    back = media_from_json(file.path, stored)
    assert back == file
    # A StrEnum equals its plain string, so equality alone would not show a value left unconverted.
    assert {type(t.kind) for t in back.tracks} == {TrackKind}
    assert {type(t.video.hdr) for t in back.tracks if t.video} == {HdrKind}
    assert {type(t.audio.object_audio) for t in back.tracks if t.audio} == {ObjectAudio}
    assert media_from_json(file.path, json.loads(json.dumps(media_to_json(MediaFile(file.path, "")))))


def test_the_stored_shape_is_the_one_the_format_version_was_set_for() -> None:
    # A field added to a stored type would be read back as its default from older entries: raise FORMAT_VERSION
    # in the cache module, then update this list.
    shape = {
        t.__name__: [f.name for f in fields(t)]
        for t in (
            MediaFile,
            Track,
            TrackFlags,
            VideoProperties,
            AudioProperties,
            SubtitleProperties,
            Chapter,
            ChapterName,
            Attachment,
            Language,
        )
    }
    assert FORMAT_VERSION == 1
    assert shape == {
        "MediaFile": [
            "path",
            "container",
            "duration",
            "size",
            "modified_ns",
            "title",
            "tracks",
            "chapters",
            "attachments",
            "ids_from_mkvmerge",
        ],
        "Track": ["id", "kind", "codec", "language", "name", "flags", "video", "audio", "subtitle"],
        "TrackFlags": ["default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original"],
        "VideoProperties": ["width", "height", "frame_rate", "hdr", "bit_depth"],
        "AudioProperties": ["channels", "sample_rate", "object_audio"],
        "SubtitleProperties": ["text_based"],
        "Chapter": ["start", "end", "names"],
        "ChapterName": ["language", "text"],
        "Attachment": ["id", "file_name", "mime_type", "size", "description"],
        "Language": ["alpha3", "region", "script"],
    }


def test_an_unchanged_file_is_served_from_the_cache_without_reading_it(show: Path, cache: Path) -> None:
    read = Counted()
    first = load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert names(read.calls) == ["Show S01E01.mkv", "Show S01E02.mkv"]
    progress: list[tuple[int, int]] = []
    again = load_library(
        [show],
        programs=PROGRAMS,
        read=read,
        cache=cache,
        progress=lambda done, total, _p: progress.append((done, total)),
    )
    assert len(read.calls) == 2
    assert again.items == first.items
    assert progress == [(1, 2), (2, 2)]


def test_a_changed_size_or_modification_time_reads_the_file_again(show: Path, cache: Path) -> None:
    read = Counted()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    first, second = sorted(show.iterdir())
    kept = first.stat()
    first.write_bytes(b"longer content")
    os.utime(first, ns=(kept.st_atime_ns, kept.st_mtime_ns))  # only the size differs
    stat = second.stat()
    os.utime(second, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))  # only the time differs
    read.calls.clear()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert names(read.calls) == ["Show S01E01.mkv", "Show S01E02.mkv"]
    read.calls.clear()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert read.calls == []


def test_a_file_that_is_gone_is_dropped_and_files_elsewhere_are_kept(
    show: Path, cache: Path, make: Callable[..., Path], tmp_path: Path
) -> None:
    other = make("Other/Other S01E01.mkv")
    read = Counted()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    load_library([other.parent], programs=PROGRAMS, read=read, cache=cache)
    (show / "Show S01E02.mkv").unlink()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    stored = json.loads(cache.read_text(encoding="utf-8"))["entries"]
    assert sorted(Path(k).name for k in stored) == ["Other S01E01.mkv", "Show S01E01.mkv"]


@pytest.mark.parametrize(
    "content",
    [
        "{ not json",
        "[]",
        json.dumps({"format": FORMAT_VERSION + 1, "entries": {}}),
        json.dumps({"format": FORMAT_VERSION, "entries": []}),
    ],
    ids=["corrupt", "not an object", "another version", "entries not an object"],
)
def test_a_cache_that_cannot_be_used_is_ignored_and_built_again(show: Path, cache: Path, content: str) -> None:
    cache.parent.mkdir(parents=True)
    cache.write_text(content, encoding="utf-8")
    read = Counted()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert len(read.calls) == 2
    assert json.loads(cache.read_text(encoding="utf-8"))["format"] == FORMAT_VERSION
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert len(read.calls) == 2


def test_an_entry_that_cannot_be_read_back_reads_the_file_again(show: Path, cache: Path) -> None:
    read = Counted()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    data = json.loads(cache.read_text(encoding="utf-8"))
    for entry in data["entries"].values():
        entry["file"]["tracks"][0]["kind"] = "hologram"
    cache.write_text(json.dumps(data), encoding="utf-8")
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert len(read.calls) == 4


@pytest.mark.parametrize(
    "programs",
    [
        Programs(Path("mkvmerge"), Path("mkvextract")),
        Programs(Path("mkvmerge"), None, Path("ffprobe")),
        Programs(Path("other/mkvmerge"), Path("mkvextract"), Path("ffprobe")),
    ],
    ids=["ffprobe gone", "mkvextract gone", "mkvmerge moved"],
)
def test_other_reading_programs_read_the_file_again(show: Path, cache: Path, programs: Programs) -> None:
    read = Counted()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    load_library([show], programs=programs, read=read, cache=cache)
    assert len(read.calls) == 4


def test_a_file_that_could_not_be_read_is_tried_again_next_time(show: Path, cache: Path) -> None:
    read = Counted()
    read.fail = {"Show S01E01.mkv"}
    load = load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert [f.path.name for f in load.failures] == ["Show S01E01.mkv"]
    read.fail = set()
    read.calls.clear()
    again = load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert names(read.calls) == ["Show S01E01.mkv"]
    assert again.failures == ()


def test_a_file_that_fails_after_a_change_loses_its_entry(show: Path, cache: Path) -> None:
    read = Counted()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    (show / "Show S01E01.mkv").write_bytes(b"damaged")
    read.fail = {"Show S01E01.mkv"}
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    stored = json.loads(cache.read_text(encoding="utf-8"))["entries"]
    assert [Path(k).name for k in stored] == ["Show S01E02.mkv"]


def test_a_cancelled_read_saves_what_it_read(show: Path, cache: Path) -> None:
    cancel = threading.Event()
    read = Counted()
    load = load_library(
        [show], programs=PROGRAMS, read=read, cache=cache, cancel=cancel, progress=lambda *_: cancel.set()
    )
    assert load.cancelled
    assert names(read.calls) == ["Show S01E01.mkv"]
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert names(read.calls) == ["Show S01E01.mkv", "Show S01E02.mkv"]


def test_a_hit_takes_the_scanned_path_and_the_size_and_time_from_the_disk(show: Path, cache: Path) -> None:
    read = Counted()
    load_library([show], programs=PROGRAMS, read=read, cache=cache)
    entry = next(iter(json.loads(cache.read_text(encoding="utf-8"))["entries"].values()))
    stat = (show / "Show S01E01.mkv").stat()
    assert (entry["size"], entry["modified_ns"]) == (stat.st_size, stat.st_mtime_ns)
    again = load_library([show], programs=PROGRAMS, read=read, cache=cache)
    assert [i.file.path for i in again.items] == sorted(show.iterdir())
    assert again.items[0].file == rich_file(show / "Show S01E01.mkv")


def test_saving_fails_quietly(show: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("", encoding="utf-8")
    load = load_library([show], programs=PROGRAMS, read=Counted(), cache=blocked / "read_cache.json")
    assert len(load.items) == 2
    assert "Could not save the read cache" in caplog.text


def test_without_a_cache_file_nothing_is_stored(show: Path, tmp_path: Path) -> None:
    load_library([show], programs=PROGRAMS, read=Counted())
    assert not list(tmp_path.glob("**/*.json"))
