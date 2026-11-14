"""The default templates against the names expected for common source, HDR and audio presets."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from showrunner.core.media import MediaItem
from showrunner.core.naming import NamingContext, NamingOptions, preview
from showrunner.core.track import HdrKind, ObjectAudio, Track

MakeItem = Callable[..., MediaItem]
Build = Callable[..., Track]

DDP = ("A_EAC3", 6, ObjectAudio.NONE)
AAC = ("A_AAC", 6, ObjectAudio.NONE)
DDP_ATMOS = ("A_EAC3", 6, ObjectAudio.ATMOS)
DDP_NAME = "Dolby Digital Plus 5.1"
ATMOS_NAME = "Dolby Digital Plus with Dolby Atmos 5.1"
NONE, HDR, HDR_PLUS, DV = HdrKind.NONE, HdrKind.HDR10, HdrKind.HDR10_PLUS, HdrKind.DOLBY_VISION

# preset, picture, HDR kind, source typed for the batch, audio, expected video name, expected audio name
CASES = [
    ("1080p Bluray AAC", (1920, 1080), NONE, "Bluray", AAC, "1080p Bluray", "AAC 5.1"),
    ("1080p Bluray DDP", (1920, 800), NONE, "Bluray", DDP, "1080p Bluray", DDP_NAME),
    ("1080p WEB-DL AAC", (1920, 1080), NONE, "WEB-DL", AAC, "1080p WEB-DL", "AAC 5.1"),
    ("1080p WEB-DL DDP", (1920, 1080), NONE, "WEB-DL", DDP, "1080p WEB-DL", DDP_NAME),
    ("1080p Webrip AAC", (1920, 1080), NONE, "Webrip", AAC, "1080p Webrip", "AAC 5.1"),
    ("2160p HDR WEB-DL DDP", (3840, 2160), HDR, "WEB-DL", DDP, "2160p HDR WEB-DL", DDP_NAME),
    ("2160p HDR10+ WEB-DL DDP", (3840, 2160), HDR_PLUS, "WEB-DL", DDP, "2160p HDR10+ WEB-DL", DDP_NAME),
    ("2160p Hybrid Bluray DDP", (3840, 2160), DV, "Hybrid Bluray", DDP, "2160p HDR/DV Hybrid Bluray", DDP_NAME),
    ("2160p Hybrid WEB-DL DDP", (3840, 2160), DV, "Hybrid WEB-DL", DDP, "2160p HDR/DV Hybrid WEB-DL", DDP_NAME),
    ("2160p Hybrid WEBRIP DDP", (3840, 1600), DV, "Hybrid Webrip", DDP_ATMOS, "2160p HDR/DV Hybrid Webrip", ATMOS_NAME),
    ("2160p WEB-DL DDP", (3840, 2160), NONE, "Web-DL", DDP_ATMOS, "2160p Web-DL", ATMOS_NAME),
    ("576p DVD AAC 2.0", (720, 576), NONE, "DVD", ("A_AAC", 2, ObjectAudio.NONE), "576p DVD", "AAC 2.0"),
]


def names(item: MediaItem, track: Track, source: str, options: NamingOptions) -> dict[str, str]:
    context = NamingContext(item, track, source, options.custom_tokens, options.value_maps)
    templates = {
        "title": options.title_template,
        "video": options.video_track_template,
        "audio": options.audio_track_template,
        "subtitle": options.subtitle_track_template,
    }
    return {kind: preview(template, context).text for kind, template in templates.items()}


@pytest.mark.parametrize(("preset", "size", "hdr", "source", "audio_spec", "video_name", "audio_name"), CASES)
def test_defaults_name_each_preset(
    make_item: MakeItem,
    video: Build,
    audio: Build,
    subtitle: Build,
    base: str,
    preset: str,
    size: tuple[int, int],
    hdr: HdrKind,
    source: str,
    audio_spec: tuple[str, int, ObjectAudio],
    video_name: str,
    audio_name: str,
) -> None:
    picture, sound, text = video(*size, hdr), audio(*audio_spec), subtitle()
    item = make_item(picture, sound, text)
    options = NamingOptions()
    assert names(item, picture, source, options)["video"] == f"{base} ({video_name})", preset
    assert names(item, sound, source, options)["audio"] == f"{base} ({audio_name})", preset
    assert names(item, text, source, options)["subtitle"] == base
    assert names(item, picture, source, options)["title"] == base


def test_two_audio_tracks(make_item: MakeItem, video: Build, audio: Build, base: str) -> None:
    atmos, plain = audio("A_TRUEHD", 8, ObjectAudio.ATMOS), audio("A_EAC3", 6, track_id=2)
    item = make_item(video(3840, 2160, DV), atmos, plain)
    options = NamingOptions()
    assert names(item, atmos, "Hybrid Bluray", options)["audio"] == f"{base} (Dolby Atmos 7.1)"
    assert names(item, plain, "Hybrid Bluray", options)["audio"] == f"{base} (Dolby Digital Plus 5.1)"


def test_overrides_name_the_remaining_presets(make_item: MakeItem, video: Build, audio: Build, base: str) -> None:
    # DTS-HD Master Audio and `HDR10+/DV` come from value maps.
    dts, picture = audio("A_DTS", 6), video(3840, 2160, DV)
    item = make_item(picture, dts)
    options = NamingOptions(value_maps={"codec": {"DTS": "DTS-HD Master Audio"}, "hdr": {"HDR/DV": "HDR10+/DV"}})
    assert names(item, dts, "Hybrid WEB-DL", options)["audio"] == f"{base} (DTS-HD Master Audio 5.1)"
    assert names(item, picture, "Hybrid WEB-DL", options)["video"] == f"{base} (2160p HDR10+/DV Hybrid WEB-DL)"


def test_atmos_after_the_channels_with_a_user_template(
    make_item: MakeItem, video: Build, audio: Build, base: str
) -> None:
    sound = audio("A_EAC3", 6, ObjectAudio.ATMOS)
    item = make_item(video(), sound)
    options = NamingOptions(
        audio_track_template="{file_name} ({codec} {channels}[ with {atmos}])",
        value_maps={"codec": {"Dolby Digital Plus with Dolby Atmos": "Dolby Digital Plus"}},
    )
    assert names(item, sound, "", options)["audio"] == f"{base} (Dolby Digital Plus 5.1 with Dolby Atmos)"


def test_sparse_names_do_not_leave_empty_brackets(make_item: MakeItem, video: Build) -> None:
    picture = video(1920, 1080)
    item = make_item(picture, stem="Plain Name")
    assert names(item, picture, "", NamingOptions())["video"] == "Plain Name (1080p)"
