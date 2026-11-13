from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from showrunner.core.language import Language
from showrunner.core.track import HdrKind, ObjectAudio, TrackFlags
from showrunner.tools.probe import MissingProgramsError, ProbeError, Programs, probe

BOTH = Programs(Path("mkvmerge.exe"), Path("mkvextract.exe"), Path("ffprobe.exe"))
MKVTOOLNIX_ONLY = Programs(Path("mkvmerge.exe"), Path("mkvextract.exe"))
FFPROBE_ONLY = Programs(ffprobe=Path("ffprobe.exe"))
PQ_FRAME = {"frames": [{"side_data_list": [{"side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"}]}, {}]}


def video_stream(data: dict) -> dict:
    return next(s for s in data["streams"] if s["codec_type"] == "video")


def test_both_programs_give_mkvmerges_tracks_with_ffprobes_details(recorded, fake_tools, media_file) -> None:
    tools = fake_tools(recorded("truehd_ac3_pgs"))
    media = probe(media_file, BOTH)
    video, truehd, *_ = media.tracks
    assert media.ids_from_mkvmerge
    assert [(t.id, t.codec) for t in media.tracks] == [
        (0, "V_MPEGH/ISO/HEVC"),
        (1, "A_TRUEHD"),
        (2, "A_AC3"),
        (3, "A_AC3"),
        (4, "S_HDMV/PGS"),
    ]
    assert (video.video.bit_depth, video.video.hdr) == (10, HdrKind.NONE)
    assert video.video.frame_rate == pytest.approx(23.976, abs=0.001)
    assert truehd.audio.object_audio is ObjectAudio.NONE
    assert len(media.chapters) == 6
    assert tools.calls == ["mkvmerge", "mkvextract", "ffprobe"]  # an ordinary file never decodes frames


def test_a_text_track_in_another_language_and_its_chapters(recorded, fake_tools, media_file) -> None:
    fake_tools(recorded("ac3_srt_turkish"))
    media = probe(media_file, BOTH)
    (subtitle,) = media.subtitle_tracks
    assert (subtitle.language, subtitle.subtitle.text_based) == (Language("tur"), True)
    assert len(media.chapters) == 7


def test_pq_video_is_hdr10_and_dynamic_metadata_in_the_first_frames_makes_it_hdr10_plus(
    recorded, fake_tools, media_file
) -> None:
    data = recorded("truehd_pgs")
    video_stream(data.ffprobe)["color_transfer"] = "smpte2084"
    tools = fake_tools(data)
    assert probe(media_file, BOTH).video_tracks[0].video.hdr is HdrKind.HDR10
    assert tools.calls.count("frames") == 1

    tools.frames = PQ_FRAME
    assert probe(media_file, BOTH).video_tracks[0].video.hdr is HdrKind.HDR10_PLUS


def test_dolby_vision_is_known_from_the_stream_without_reading_frames(recorded, fake_tools, media_file) -> None:
    data = recorded("truehd_pgs")
    video_stream(data.ffprobe).update(
        color_transfer="smpte2084", side_data_list=[{"side_data_type": "DOVI configuration record"}]
    )
    tools = fake_tools(data)
    assert probe(media_file, BOTH).video_tracks[0].video.hdr is HdrKind.DOLBY_VISION
    assert "frames" not in tools.calls


def test_atmos_is_read_from_the_audio_profile(recorded, fake_tools, media_file) -> None:
    data = recorded("truehd_pgs")
    truehd = next(s for s in data.ffprobe["streams"] if s["codec_name"] == "truehd")
    truehd["profile"] = "Dolby TrueHD + Dolby Atmos"
    fake_tools(data)
    assert probe(media_file, BOTH).audio_tracks[0].audio.object_audio is ObjectAudio.ATMOS


def test_every_flag_and_attachment_survives_the_combination(recorded, fake_tools, media_file) -> None:
    fake_tools(recorded("flags_attachment"))
    media = probe(media_file, BOTH)
    assert media.tracks[4].flags == TrackFlags(forced=True, hearing_impaired=True)
    assert [a.file_name for a in media.attachments] == ["font.txt"]
    assert media.chapters[0].name_for(Language("tur")) == "Giris"


def test_streams_that_do_not_line_up_leave_mkvmerges_view_alone(recorded, fake_tools, media_file) -> None:
    data = recorded("truehd_pgs")
    data.ffprobe["streams"][1]["profile"] = "Dolby TrueHD + Dolby Atmos"
    data.ffprobe["streams"][1], data.ffprobe["streams"][2] = data.ffprobe["streams"][2], data.ffprobe["streams"][1]
    fake_tools(data)
    media = probe(media_file, BOTH)
    assert media.ids_from_mkvmerge
    assert [t.codec for t in media.tracks] == ["V_MPEGH/ISO/HEVC", "A_TRUEHD", "S_HDMV/PGS"]
    assert media.video_tracks[0].video.bit_depth is None
    assert media.audio_tracks[0].audio.object_audio is ObjectAudio.NONE


def test_without_ffprobe_mkvmerge_alone_builds_the_file(recorded, fake_tools, media_file) -> None:
    tools = fake_tools(recorded("truehd_ac3_pgs"))
    media = probe(media_file, MKVTOOLNIX_ONLY)
    assert tools.calls == ["mkvmerge", "mkvextract"]
    assert media.ids_from_mkvmerge
    assert media.video_tracks[0].video.bit_depth is None
    assert media.video_tracks[0].video.frame_rate == pytest.approx(23.976, abs=0.001)


def test_a_failing_ffprobe_leaves_mkvmerges_view_alone(recorded, fake_tools, media_file) -> None:
    tools = fake_tools(recorded("truehd_ac3_pgs"))
    tools.ffprobe_exit = 1
    media = probe(media_file, BOTH)
    assert media.ids_from_mkvmerge
    assert media.video_tracks[0].video.bit_depth is None


def test_without_mkvmerge_ffprobe_alone_builds_the_file_and_marks_the_ids(recorded, fake_tools, media_file) -> None:
    tools = fake_tools(recorded("flags_attachment"))
    media = probe(media_file, FFPROBE_ONLY)
    assert tools.calls == ["ffprobe"]
    assert not media.ids_from_mkvmerge
    assert (media.container, media.title) == ("Matroska", "Sample Title")
    assert media.duration == pytest.approx(10.432)
    video, truehd, visual, commentary, subtitle = media.tracks
    assert [t.id for t in media.tracks] == [0, 1, 2, 3, 4]
    assert (video.codec, video.video.width, video.video.bit_depth) == ("V_MPEGH/ISO/HEVC", 1920, 10)
    assert (truehd.codec, truehd.language, truehd.audio.channels) == ("A_TRUEHD", Language("eng"), 6)
    assert visual.language == Language("por")
    assert commentary.flags.commentary
    assert (subtitle.codec, subtitle.flags.forced, subtitle.subtitle.text_based) == ("S_HDMV/PGS", True, False)
    assert [(a.id, a.file_name) for a in media.attachments] == [(1, "font.txt")]
    # ffprobe reports one title per chapter and no language, so names per language need mkvextract.
    assert (media.chapters[1].start, media.chapters[1].end) == (2.5, 4.0)
    assert (media.chapters[1].names[0].language, media.chapters[1].names[0].text) == (None, "Scene")


def test_a_file_mkvmerge_rejects_is_still_read_by_ffprobe(recorded, fake_tools, media_file) -> None:
    data = recorded("truehd_pgs")
    data.mkvmerge["container"]["supported"] = False
    fake_tools(data)
    media = probe(media_file, BOTH)
    assert not media.ids_from_mkvmerge
    assert len(media.tracks) == 3


def test_a_file_neither_program_can_read_is_an_error_naming_both(recorded, fake_tools, media_file) -> None:
    data = recorded("truehd_pgs")
    data.mkvmerge["container"]["supported"] = False
    tools = fake_tools(data)
    tools.ffprobe_exit = 1
    with pytest.raises(ProbeError, match=r"mkvmerge: .*ffprobe: Invalid data"):
        probe(media_file, BOTH)


def test_without_either_program_the_error_names_both() -> None:
    with pytest.raises(MissingProgramsError, match="mkvtoolnix, ffmpeg") as caught:
        probe(Path("anything.mkv"), Programs())
    assert caught.value.missing == ("mkvtoolnix", "ffmpeg")


def test_a_file_that_does_not_exist_is_reported_as_such(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        probe(tmp_path / "gone.mkv", BOTH)


def test_cancellation_and_timeouts_are_not_swallowed(media_file, monkeypatch: pytest.MonkeyPatch) -> None:
    from showrunner.tools.process import ProcessTimeoutError

    def slow(args, **_):
        raise ProcessTimeoutError("no result after 1 s", args)

    monkeypatch.setattr("showrunner.tools.mkvtoolnix.identify.run", slow)
    with pytest.raises(ProcessTimeoutError):
        probe(media_file, BOTH, timeout=1, cancel=threading.Event())


@pytest.mark.skipif(not os.environ.get("SHOWRUNNER_TEST_MEDIA"), reason="SHOWRUNNER_TEST_MEDIA names no file")
def test_a_real_file_is_probed_with_the_installed_programs() -> None:
    from showrunner.app.dependencies import service

    programs = service.media_programs()
    if programs.mkvmerge is None or programs.ffprobe is None:
        pytest.skip("MKVToolNix and FFmpeg are both needed")
    media = service.probe_file(Path(os.environ["SHOWRUNNER_TEST_MEDIA"]), programs)
    assert media.ids_from_mkvmerge
    assert media.video_tracks
    assert media.video_tracks[0].video.bit_depth is not None
