"""The track order through the mux: the plan, the mkvmerge arguments it makes, and the check of the new file."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, SubtitleFile
from showrunner.core.naming import NamingOptions
from showrunner.core.track import AudioProperties
from showrunner.stages.metadata import MetadataOptions
from showrunner.stages.mux import MuxOptions, MuxPlan, plan_mux
from showrunner.stages.mux import apply as module
from showrunner.stages.tracks import KindTest, PairedFile, TrackMatch, TracksOptions
from showrunner.tools.mkvtoolnix.merge import build_arguments

# Names stay as they are, so only the order differs between the plan and the file.
KEEP_NAMES = NamingOptions(
    title_template="", video_track_template="", audio_track_template="", subtitle_track_template=""
)
FRENCH_FIRST = TracksOptions(order=[TrackMatch(kind=KindTest.AUDIO, languages=["fr"])])


def mux(item: MediaItem, tracks: TracksOptions) -> MuxPlan:
    result = plan_mux(item, MuxOptions(), tracks, MetadataOptions(), KEEP_NAMES)
    assert isinstance(result, MuxPlan)
    return result


def two_audio(b: SimpleNamespace) -> MediaItem:
    return b.item(b.video(0), b.audio(1, "English", "eng", default=True), b.audio(2, "French", "fre"))


def test_an_order_alone_plans_a_new_file_with_the_tracks_in_that_order(b: SimpleNamespace) -> None:
    item = two_audio(b)
    assert plan_mux(item, MuxOptions(), TracksOptions(), MetadataOptions(), KEEP_NAMES) is None
    plan = mux(item, FRENCH_FIRST)
    assert [t.planned.track.id for t in plan.tracks] == [0, 2, 1]


def test_the_mkvmerge_arguments_carry_the_order(b: SimpleNamespace) -> None:
    srt = SubtitleFile(Path("Show Name - S01E01.tr.srt"), Language("tur"))
    item = b.item(
        b.video(0), b.audio(1, "English", "eng"), b.audio(2, "French", "fre"), b.subtitle(3), subtitles=(srt,)
    )
    order = [*FRENCH_FIRST.order, TrackMatch(kind=KindTest.SUBTITLE, languages=["tr"])]
    plan = mux(item, TracksOptions(add_paired=[PairedFile.of(srt)], order=order))
    arguments = build_arguments(module._merge_spec(plan, plan.partial))
    # The subtitle file is the second source; it goes ahead of the embedded subtitle.
    assert arguments[-2:] == ["--track-order", "0:0,0:2,0:1,1:0,0:3"]


def test_the_check_catches_tracks_in_another_order(b: SimpleNamespace) -> None:
    item = two_audio(b)
    plan = mux(item, FRENCH_FIRST)
    # mkvmerge numbers the tracks of the new file again, in the order it wrote them.
    right = MediaFile(
        Path("new.mkv"), "matroska", tracks=tuple(replace(t.planned.track, flags=t.flags) for t in plan.tracks)
    )
    assert module.verify(plan, right) == ()
    wrong = replace(right, tracks=(right.tracks[0], right.tracks[2], right.tracks[1]))
    problems = module.verify(plan, wrong)
    assert {(p.what, p.position) for p in problems} >= {("language", 1), ("language", 2), ("name", 1), ("name", 2)}


def test_the_check_tells_apart_tracks_that_differ_only_in_channels(b: SimpleNamespace) -> None:
    surround = b.audio(1, "English", "eng", default=True)
    stereo = replace(surround, id=2, flags=replace(surround.flags, default=False), audio=AudioProperties(2))
    item = b.item(b.video(0), surround, stereo)
    stereo_first = TracksOptions(order=[TrackMatch(kind=KindTest.AUDIO, max_channels=2)])
    plan = mux(item, stereo_first)
    assert [t.planned.track.id for t in plan.tracks] == [0, 2, 1]
    in_file_order = tuple(replace(t, flags=p.flags) for t, p in zip(item.file.tracks, plan.tracks, strict=True))
    problems = module.verify(plan, MediaFile(Path("new.mkv"), "matroska", tracks=in_file_order))
    assert {(p.what, p.position) for p in problems} == {("channels", 1), ("channels", 2)}
    # A remux that keeps the file's order is not held to the channels.
    assert (
        module.verify(replace(plan, reordered=False), MediaFile(Path("new.mkv"), "matroska", tracks=in_file_order))
        == ()
    )
