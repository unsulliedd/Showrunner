from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from showrunner.core.media import Episode, MediaItem
from showrunner.core.naming import TOKENS, NamingContext, preview
from showrunner.core.track import HdrKind, ObjectAudio, Track

MakeItem = Callable[..., MediaItem]
Build = Callable[..., Track]


def value(token: str, context: NamingContext) -> str:
    return preview("{" + token + "}", context).text


def test_every_token_is_documented_with_an_example() -> None:
    assert all(token.example and token.name == name for name, token in TOKENS.items())


def test_item_tokens_of_an_episode(episode_context: NamingContext, base: str) -> None:
    values = {name: value(name, episode_context) for name in TOKENS}
    assert values["show"] == "Show Name"
    assert values["title"] == "Show Name"
    assert values["movie"] == ""
    assert values["year"] == "2020"
    assert (values["season"], values["episode"], values["episode_title"]) == ("1", "5", "Episode Name")
    assert values["file_name"] == base


def test_item_tokens_of_a_movie(make_item: MakeItem) -> None:
    context = NamingContext(make_item(movie=True, stem="Movie Title (2021)"))
    assert [value(n, context) for n in ("title", "movie", "show", "year", "season", "file_name")] == [
        "Movie Title",
        "Movie Title",
        "",
        "2021",
        "",
        "Movie Title (2021)",
    ]


def test_season_zero_is_a_value(make_item: MakeItem) -> None:
    item = make_item()
    assert isinstance(item.identity, Episode)
    item = replace(item, identity=replace(item.identity, season=0))
    assert preview("{season:00}", NamingContext(item)).text == "00"


def test_source_prefers_the_batch_value_then_the_release_name(make_item: MakeItem) -> None:
    item = make_item(stem="Show.Name.S01E05.1080p.WEB-DL.DDP5.1")
    assert value("source", NamingContext(item)) == "WEB-DL"
    assert value("source", NamingContext(item, source="Hybrid Bluray")) == "Hybrid Bluray"
    assert value("source", NamingContext(make_item(stem="Show Name"))) == ""


def test_video_tokens_come_from_the_first_video_track_for_any_track(
    make_item: MakeItem, video: Build, audio: Build, subtitle: Build
) -> None:
    item = make_item(video(3840, 1600, HdrKind.DOLBY_VISION, 10), audio(), subtitle())
    for track in (None, *item.file.tracks):
        context = NamingContext(item, track)
        assert value("resolution", context) == "2160p"
        assert value("hdr", context) == "HDR/DV"
        assert value("video_codec", context) == "HEVC"
        assert value("bit_depth", context) == "10"


def test_video_tokens_are_empty_without_video(make_item: MakeItem, audio: Build) -> None:
    context = NamingContext(make_item(audio()))
    assert [value(n, context) for n in ("resolution", "hdr", "video_codec", "bit_depth")] == ["", "", "", ""]


def test_hdr_combinations(make_item: MakeItem, video: Build) -> None:
    def hdr(kind: HdrKind, **names: str) -> str:
        return value("hdr", NamingContext(make_item(video(hdr=kind)), value_maps={"hdr": names}))

    assert hdr(HdrKind.NONE) == ""
    assert hdr(HdrKind.HDR10) == "HDR"
    assert hdr(HdrKind.HDR10_PLUS) == "HDR10+"
    assert hdr(HdrKind.DOLBY_VISION) == "HDR/DV"
    assert hdr(HdrKind.HLG) == "HLG"
    assert hdr(HdrKind.DOLBY_VISION, **{"HDR/DV": "DV HDR10"}) == "DV HDR10"


def test_audio_tokens(make_item: MakeItem, video: Build, audio: Build) -> None:
    track = audio("A_TRUEHD", 8, ObjectAudio.ATMOS, default=True, forced=True)
    context = NamingContext(make_item(video(), track), track)
    assert value("codec", context) == "Dolby Atmos"
    assert value("channels", context) == "7.1"
    assert value("object_audio", context) == "Dolby Atmos"
    assert value("atmos", context) == "Dolby Atmos"
    assert value("language", context) == "English"
    assert value("language_code", context) == "en"
    assert value("track_name", context) == "Original Name"
    assert value("flags", context) == "Default Forced"


def test_atmos_and_flags_are_empty_for_plain_audio(make_item: MakeItem, video: Build, audio: Build) -> None:
    track = audio()
    context = NamingContext(make_item(video(), track), track)
    assert (value("atmos", context), value("flags", context)) == ("", "")


def test_codec_falls_back_to_the_raw_id_and_takes_overrides(make_item: MakeItem, video: Build, audio: Build) -> None:
    track = audio("A_MADE_UP")
    item = make_item(video(), track)
    assert value("codec", NamingContext(item, track)) == "A_MADE_UP"
    assert value("codec", NamingContext(item, track, value_maps={"codec": {"A_MADE_UP": "Made Up"}})) == "Made Up"


def test_subtitle_track_tokens(make_item: MakeItem, video: Build, subtitle: Build) -> None:
    track = subtitle()
    context = NamingContext(make_item(video(), track), track)
    assert value("codec", context) == "SubRip"
    assert value("language", context) == "Turkish"
    assert value("channels", context) == ""
