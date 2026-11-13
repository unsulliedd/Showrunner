from __future__ import annotations

from pathlib import Path

import pytest

from showrunner.core.language import Language
from showrunner.core.track import SubtitleProperties, TrackFlags
from showrunner.tools.mkvtoolnix.identify import MkvmergeError, has_chapters, identify, parse_identification

MKVMERGE = Path("mkvmerge.exe")
MKVEXTRACT = Path("mkvextract.exe")
TIMEOUT = 5.0


def test_a_recorded_file_gives_mkvmerges_ids_codec_ids_and_properties(recorded, media_file) -> None:
    media = parse_identification(recorded("truehd_ac3_pgs").mkvmerge, media_file)
    video, truehd, ac3, commentary, subtitle = media.tracks
    assert [t.id for t in media.tracks] == [0, 1, 2, 3, 4]
    assert media.container == "Matroska"
    assert media.title == "Example Show S01E02 Second Episode"
    assert media.duration == pytest.approx(1327.618)
    assert media.size == 10
    assert video.codec == "V_MPEGH/ISO/HEVC"
    assert (video.video.width, video.video.height) == (1920, 1080)
    assert video.video.frame_rate == pytest.approx(23.976, abs=0.001)
    assert video.language is None  # "und"
    assert (truehd.codec, truehd.language, truehd.name) == ("A_TRUEHD", Language("eng"), "TrueHD 5.1")
    assert (truehd.audio.channels, truehd.audio.sample_rate) == (6, 48000)
    assert truehd.flags == TrackFlags(default=True)
    assert (ac3.codec, ac3.flags.default, commentary.audio.channels) == ("A_AC3", False, 2)
    assert (subtitle.codec, subtitle.subtitle) == ("S_HDMV/PGS", SubtitleProperties(text_based=False))


def test_a_text_subtitle_is_text_based_and_the_language_is_the_ietf_one(recorded, media_file) -> None:
    subtitle = parse_identification(recorded("ac3_srt_turkish").mkvmerge, media_file).subtitle_tracks[0]
    assert (subtitle.codec, subtitle.language, subtitle.subtitle.text_based) == ("S_TEXT/UTF8", Language("tur"), True)


def test_every_flag_attachments_and_regional_languages_are_read(recorded, media_file) -> None:
    media = parse_identification(recorded("flags_attachment").mkvmerge, media_file)
    assert media.title == "Sample Title"
    assert media.tracks[1].flags == TrackFlags(default=True, original=True)
    assert media.tracks[2].flags == TrackFlags(visual_impaired=True)
    assert media.tracks[2].language == Language("por", "BR")
    assert media.tracks[3].flags == TrackFlags(commentary=True)
    assert media.tracks[4].flags == TrackFlags(forced=True, hearing_impaired=True)
    (attachment,) = media.attachments
    assert (attachment.id, attachment.file_name, attachment.size, attachment.description) == (
        1,
        "font.txt",
        17,
        "A font",
    )


def test_a_track_that_is_not_video_audio_or_subtitles_is_skipped(recorded, media_file) -> None:
    data = recorded("truehd_pgs").mkvmerge
    data["tracks"].append({"id": 9, "type": "buttons", "codec": "VobBtn", "properties": {}})
    assert [t.id for t in parse_identification(data, media_file).tracks] == [0, 1, 2]


def test_chapters_are_read_only_when_the_file_has_some(recorded, media_file, fake_tools) -> None:
    data = recorded("truehd_pgs")
    assert has_chapters(data.mkvmerge)
    tools = fake_tools(data)
    media = identify(MKVMERGE, media_file, mkvextract=MKVEXTRACT, timeout=TIMEOUT)
    assert len(media.chapters) > 0
    assert tools.calls == ["mkvmerge", "mkvextract"]

    data.mkvmerge["chapters"] = []
    tools = fake_tools(data)
    assert identify(MKVMERGE, media_file, mkvextract=MKVEXTRACT, timeout=TIMEOUT).chapters == ()
    assert tools.calls == ["mkvmerge"]


def test_chapters_are_skipped_without_mkvextract(recorded, media_file, fake_tools) -> None:
    tools = fake_tools(recorded("truehd_pgs"))
    assert identify(MKVMERGE, media_file, timeout=TIMEOUT).chapters == ()
    assert tools.calls == ["mkvmerge"]


def test_a_file_mkvmerge_cannot_read_is_an_error_with_its_message(recorded, media_file, fake_tools) -> None:
    data = recorded("truehd_pgs")
    data.mkvmerge.update(errors=["The file is not recognized."])
    data.mkvmerge["container"]["supported"] = False
    fake_tools(data)
    with pytest.raises(MkvmergeError, match="not recognized"):
        identify(MKVMERGE, media_file, timeout=TIMEOUT)


def test_warnings_alone_do_not_fail_the_identification(recorded, media_file, fake_tools) -> None:
    tools = fake_tools(recorded("truehd_pgs"))
    tools.mkvmerge_exit = 1
    assert len(identify(MKVMERGE, media_file, timeout=TIMEOUT).tracks) == 3
