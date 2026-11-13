from __future__ import annotations

import pytest

from showrunner.core.track import AudioProperties, Track, TrackKind, VideoProperties
from showrunner.tools.ffmpeg.streams import track_streams
from showrunner.tools.mkvtoolnix.identify import parse_identification
from showrunner.tools.probe.matching import codec_id_for, is_text_subtitle, match_streams


def tracks_and_streams(recorded, media_file, name: str = "truehd_ac3_pgs"):
    data = recorded(name)
    return parse_identification(data.mkvmerge, media_file).tracks, track_streams(data.ffprobe)


def test_a_recorded_file_lines_up_by_position(recorded, media_file) -> None:
    tracks, streams = tracks_and_streams(recorded, media_file)
    assert match_streams(tracks, streams) == streams


def test_a_different_number_of_streams_does_not_match(recorded, media_file) -> None:
    tracks, streams = tracks_and_streams(recorded, media_file)
    assert match_streams(tracks, streams[:-1]) is None


def test_swapped_streams_of_different_codecs_do_not_match(recorded, media_file) -> None:
    tracks, streams = tracks_and_streams(recorded, media_file)
    streams[1], streams[2] = streams[2], streams[1]  # TrueHD and AC-3
    assert match_streams(tracks, streams) is None


def test_swapped_streams_of_the_same_codec_but_other_channels_do_not_match(recorded, media_file) -> None:
    tracks, streams = tracks_and_streams(recorded, media_file)
    streams[2], streams[3] = streams[3], streams[2]  # 5.1 and stereo AC-3
    assert match_streams(tracks, streams) is None


def test_another_kind_in_the_same_position_does_not_match(recorded, media_file) -> None:
    tracks, streams = tracks_and_streams(recorded, media_file)
    streams[4] = {**streams[4], "codec_type": "audio"}
    assert match_streams(tracks, streams) is None


def test_a_picture_of_another_size_does_not_match() -> None:
    track = Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080))
    stream = {"codec_type": "video", "codec_name": "hevc", "width": 3840, "height": 2160}
    assert match_streams([track], [stream]) is None
    assert match_streams([track], [{**stream, "width": 1920, "height": 1080}]) is not None


def test_a_codec_the_table_does_not_know_is_judged_by_the_other_checks() -> None:
    track = Track(0, TrackKind.AUDIO, "A_MS/ACM", audio=AudioProperties(2))
    assert match_streams([track], [{"codec_type": "audio", "codec_name": "wmav2", "channels": 2}]) is not None
    assert match_streams([track], [{"codec_type": "audio", "codec_name": "wmav2", "channels": 6}]) is None


@pytest.mark.parametrize(
    ("codec_id", "codec_name"),
    [("A_AAC/MPEG4/LC", "aac"), ("A_PCM/INT/LIT", "pcm_s16le"), ("S_TEXT/SSA", "ass"), ("V_MPEG4/ISO/AVC", "h264")],
)
def test_codec_ids_with_suffixes_match_their_ffprobe_names(codec_id: str, codec_name: str) -> None:
    kind = TrackKind(
        {"V": "video", "A": "audio", "S": "subtitle"}[codec_id[0]],
    )
    assert match_streams([Track(0, kind, codec_id)], [{"codec_type": kind.value, "codec_name": codec_name}])


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("truehd", "A_TRUEHD"),
        ("hevc", "V_MPEGH/ISO/HEVC"),
        ("hdmv_pgs_subtitle", "S_HDMV/PGS"),
        ("pcm_s24le", "A_PCM"),
        ("wmav2", "wmav2"),
    ],
)
def test_ffprobe_names_map_to_matroska_codec_ids(name: str, expected: str) -> None:
    assert codec_id_for(name) == expected


def test_picture_subtitles_are_not_text() -> None:
    assert not is_text_subtitle("hdmv_pgs_subtitle")
    assert is_text_subtitle("subrip")
