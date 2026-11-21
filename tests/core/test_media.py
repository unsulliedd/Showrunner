import dataclasses
from pathlib import Path

import pytest

from showrunner.core.language import Language
from showrunner.core.media import Attachment, Chapter, ChapterName, Episode, MediaFile, MediaItem, Movie, SubtitleFile
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

TURKISH = Language("tur")
ENGLISH = Language("eng")


def make_file() -> MediaFile:
    return MediaFile(
        path=Path("Show.S01E01.mkv"),
        container="Matroska",
        tracks=(
            Track(0, TrackKind.VIDEO, "HEVC", video=VideoProperties(3840, 2160, 23.976, HdrKind.DOLBY_VISION, 10)),
            Track(1, TrackKind.AUDIO, "TrueHD", ENGLISH, audio=AudioProperties(8, 48000, ObjectAudio.ATMOS)),
            Track(2, TrackKind.AUDIO, "AAC", TURKISH, audio=AudioProperties(2)),
            Track(3, TrackKind.SUBTITLE, "SubRip", TURKISH, flags=TrackFlags(forced=True)),
        ),
    )


def test_accessors_filter_by_kind_in_file_order() -> None:
    media = make_file()
    assert [t.id for t in media.video_tracks] == [0]
    assert [t.id for t in media.audio_tracks] == [1, 2]
    assert [t.id for t in media.subtitle_tracks] == [3]


def test_accessors_on_empty_file() -> None:
    media = MediaFile(Path("a.mkv"), "Matroska")
    assert media.video_tracks == media.audio_tracks == media.subtitle_tracks == ()


@pytest.mark.parametrize(
    "value",
    [
        Track(0, TrackKind.VIDEO),
        TrackFlags(),
        VideoProperties(),
        AudioProperties(),
        SubtitleProperties(),
        make_file(),
        Chapter(0.0),
        Attachment(1, "cover.jpg", "image/jpeg", 10),
        Movie("Alpha"),
        SubtitleFile(Path("a.srt")),
    ],
)
def test_types_are_immutable(value: object) -> None:
    field = dataclasses.fields(value)[0].name  # type: ignore[arg-type]
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, None)


def test_values_are_hashable() -> None:
    assert len({make_file(), make_file()}) == 1


def test_chapter_name_for_prefers_language_then_first() -> None:
    chapter = Chapter(10.0, names=(ChapterName(ENGLISH, "Opening"), ChapterName(TURKISH, "Prologue")))
    assert chapter.name_for(TURKISH) == "Prologue"
    assert chapter.name_for(Language("deu")) == "Opening"
    assert Chapter(0.0).name_for(TURKISH) is None


def test_media_item_holds_identity_file_and_subtitles() -> None:
    subtitle = SubtitleFile(Path("Show.S01E01.tr.srt"), TURKISH, forced=True)
    item = MediaItem(Episode("Show", 1, 1, year=2020, episode_title="Pilot"), make_file(), (subtitle,))
    match item.identity:
        case Episode(show=show, season=season, episode=number):
            assert (show, season, number) == ("Show", 1, 1)
        case _:
            pytest.fail("expected an episode")
    assert item.subtitles == (subtitle,)
    assert MediaItem(Movie("Alpha", 1995), make_file()).subtitles == ()
