from __future__ import annotations

import pytest

from showrunner.core.track import HdrKind, ObjectAudio
from showrunner.tools.ffmpeg import streams as ff

DOVI = {"side_data_type": "DOVI configuration record", "dv_profile": 8}
PLUS_FRAME = {"side_data_list": [{"side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"}]}


def stream(**fields) -> dict:
    return {"codec_type": "video", **fields}


@pytest.mark.parametrize(
    ("fields", "plus", "expected"),
    [
        ({"color_transfer": "bt709"}, False, HdrKind.NONE),
        ({}, False, HdrKind.NONE),
        ({"color_transfer": "smpte2084"}, False, HdrKind.HDR10),
        ({"color_transfer": "smpte2084"}, True, HdrKind.HDR10_PLUS),
        ({"color_transfer": "arib-std-b67"}, False, HdrKind.HLG),
        # A transfer other than PQ cannot carry HDR10+.
        ({"color_transfer": "bt709"}, True, HdrKind.NONE),
        ({"color_transfer": "smpte2084", "side_data_list": [DOVI]}, False, HdrKind.DOLBY_VISION),
        ({"color_transfer": "smpte2084", "side_data_list": [DOVI]}, True, HdrKind.DOLBY_VISION),
        # Profile 5 streams may leave the transfer unspecified; the configuration record still decides.
        ({"color_transfer": "unknown", "side_data_list": [DOVI]}, False, HdrKind.DOLBY_VISION),
        ({"color_transfer": "arib-std-b67", "side_data_list": [DOVI]}, False, HdrKind.DOLBY_VISION),
    ],
)
def test_hdr_kind(fields: dict, plus: bool, expected: HdrKind) -> None:
    assert ff.hdr_kind(stream(**fields), plus) is expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"color_transfer": "smpte2084"}, True),
        ({"color_transfer": "smpte2084", "side_data_list": [DOVI]}, False),
        ({"color_transfer": "arib-std-b67"}, False),
        ({"color_transfer": "bt709"}, False),
        ({}, False),
    ],
)
def test_the_frame_read_happens_only_for_pq_streams_without_dolby_vision(fields: dict, expected: bool) -> None:
    assert ff.needs_dynamic_hdr_check(stream(**fields)) is expected


@pytest.mark.parametrize(
    ("frames", "expected"),
    [
        ({"frames": [PLUS_FRAME]}, True),
        ({"frames": [{}, PLUS_FRAME]}, True),
        ({"frames": [{"side_data_list": [{"side_data_type": "Mastering display metadata"}]}]}, False),
        ({"frames": [{}]}, False),
        ({}, False),
    ],
)
def test_hdr10_plus_is_the_smpte_2094_40_side_data_of_a_frame(frames: dict, expected: bool) -> None:
    assert ff.has_hdr10_plus(frames) is expected


@pytest.mark.parametrize(
    ("codec", "profile", "expected"),
    [
        ("truehd", "Dolby TrueHD + Dolby Atmos", ObjectAudio.ATMOS),
        ("eac3", "Dolby Digital Plus + Dolby Atmos", ObjectAudio.ATMOS),
        ("dts", "DTS-HD MA + DTS:X", ObjectAudio.DTS_X),
        ("dts", "DTS-HD MA + DTS:X IMAX", ObjectAudio.DTS_X),
        ("truehd", "", ObjectAudio.NONE),
        ("eac3", "Dolby Digital Plus", ObjectAudio.NONE),
        ("dts", "DTS-HD MA", ObjectAudio.NONE),
        ("dts", "DTS-HD HRA", ObjectAudio.NONE),
        # Atmos is carried by these two codecs only.
        ("ac3", "Dolby Atmos", ObjectAudio.NONE),
        ("aac", "LC", ObjectAudio.NONE),
    ],
)
def test_object_audio_is_named_in_the_profile_of_the_codecs_that_carry_it(
    codec: str, profile: str, expected: ObjectAudio
) -> None:
    assert ff.object_audio({"codec_name": codec, "profile": profile}) is expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"pix_fmt": "yuv420p10le"}, 10),
        ({"pix_fmt": "p010le"}, 10),
        ({"pix_fmt": "yuv420p12le"}, 12),
        ({"pix_fmt": "yuv420p"}, 8),
        ({"pix_fmt": "nv12"}, 8),
        ({"pix_fmt": "yuv420p", "bits_per_raw_sample": "10"}, 10),
        ({"pix_fmt": "yuv420p", "bits_per_raw_sample": "N/A"}, 8),
        ({}, None),
    ],
)
def test_bit_depth(fields: dict, expected: int | None) -> None:
    assert ff.bit_depth(stream(**fields)) == expected


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"avg_frame_rate": "24000/1001", "r_frame_rate": "24000/1001"}, pytest.approx(23.976, abs=0.001)),
        ({"avg_frame_rate": "0/0", "r_frame_rate": "25/1"}, 25.0),
        ({"avg_frame_rate": "0/0", "r_frame_rate": "0/0"}, None),
        ({"avg_frame_rate": "1/0"}, None),
        ({"avg_frame_rate": "fast"}, None),
        ({}, None),
    ],
)
def test_frame_rate(fields: dict, expected: float | None) -> None:
    assert ff.frame_rate(stream(**fields)) == expected


def test_only_real_tracks_are_streams_of_interest() -> None:
    data = {
        "streams": [
            {"index": 0, "codec_type": "video"},
            {"index": 1, "codec_type": "video", "disposition": {"attached_pic": 1}},
            {"index": 2, "codec_type": "audio"},
            {"index": 3, "codec_type": "attachment"},
            {"index": 4, "codec_type": "data"},
            {"index": 5, "codec_type": "subtitle"},
        ]
    }
    assert [s["index"] for s in ff.track_streams(data)] == [0, 2, 5]


def test_dispositions_become_track_flags() -> None:
    flags = ff.disposition_flags(
        {"disposition": {"default": 1, "forced": 0, "hearing_impaired": 1, "comment": 1, "original": 1}}
    )
    assert (flags.default, flags.forced, flags.hearing_impaired, flags.commentary, flags.original) == (
        True,
        False,
        True,
        True,
        True,
    )
    assert not flags.visual_impaired
