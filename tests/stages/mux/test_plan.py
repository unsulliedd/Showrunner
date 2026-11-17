from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.naming import SUGGESTED_TEMPLATES, NamingOptions
from showrunner.core.track import TrackFlags
from showrunner.stages.metadata import MetadataOptions
from showrunner.stages.mux import MuxOptions, MuxPlan, MuxProblemKind, MuxRefused, NameField, Original, check_names
from showrunner.stages.mux import plan_mux as plan_mux_
from showrunner.stages.tracks import FlagShape, KindTest, PairedFile, TrackMatch, TrackRule, TracksOptions, Verdict

DROP_FRENCH = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["fre"]), verdict=Verdict.DROP)
TRACKS = TracksOptions(rules=[DROP_FRENCH])
ON = MuxOptions()
SUGGESTED = NamingOptions(**SUGGESTED_TEMPLATES)


def plan_mux(
    item: MediaItem,
    mux: MuxOptions = ON,
    tracks: TracksOptions = TRACKS,
    metadata: MetadataOptions | None = None,
    naming: NamingOptions | None = None,
) -> MuxPlan | MuxRefused | None:
    return plan_mux_(item, mux, tracks, metadata or MetadataOptions(), naming or SUGGESTED)


def two_audio(b: SimpleNamespace, **kwargs: object) -> MediaItem:
    return b.item(b.video(0), b.audio(1, "English", "eng", default=True), b.audio(2, "French", "fre"), **kwargs)


def test_nothing_to_remux_without_a_drop_or_an_added_file(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, "English", "eng"))
    assert plan_mux(item) is None


def test_no_rule_that_is_on_plans_nothing(b: SimpleNamespace) -> None:
    assert plan_mux(two_audio(b), tracks=TracksOptions()) is None
    assert plan_mux(two_audio(b), tracks=TracksOptions(rules=[replace(DROP_FRENCH, enabled=False)])) is None


def test_tracks_read_without_mkvmerge_are_refused(b: SimpleNamespace) -> None:
    result = plan_mux(two_audio(b, ids_from_mkvmerge=False))
    assert result == MuxRefused((MuxProblemKind.IDS_NOT_FROM_MKVMERGE,))


def test_a_file_whose_tracks_were_not_read_is_refused_rather_than_written_without_them(b: SimpleNamespace) -> None:
    # A read cancelled before the file leaves it as scanned: no tracks, though mkvmerge can open it.
    srt = SubtitleFile(Path("Show Name - S01E01.tr.srt"), Language("tur"))
    item = b.item(subtitles=(srt,))
    result = plan_mux(item, tracks=TracksOptions(add_paired=[PairedFile.of(srt)]))
    assert result == MuxRefused((MuxProblemKind.TRACKS_NOT_READ,))


def test_the_plan_keeps_the_rules_tracks_with_metadatas_names_and_title(b: SimpleNamespace) -> None:
    naming = replace(SUGGESTED, audio_track_template="{language}", title_template="{show} {episode}")
    result = plan_mux(two_audio(b, title="Old"), naming=naming)
    assert isinstance(result, MuxPlan)
    assert [t.planned.track.id for t in result.tracks] == [0, 1]
    assert result.tracks[1].name == "English"
    assert result.title == "Show Name 1"
    assert result.output == result.source  # a Matroska file keeps its name


def test_empty_templates_keep_names_and_title_but_the_rules_flags_are_written(b: SimpleNamespace) -> None:
    rules = [DROP_FRENCH, TrackRule(match=TrackMatch(kind=KindTest.VIDEO), default=FlagShape.FIRST)]
    empty = NamingOptions(
        title_template="", video_track_template="", audio_track_template="", subtitle_track_template=""
    )
    result = plan_mux(two_audio(b, title="Old"), tracks=replace(TRACKS, rules=rules), naming=empty)
    assert isinstance(result, MuxPlan)
    assert result.title == "Old"
    assert [t.name for t in result.tracks] == ["", "English"]
    assert result.tracks[0].flags.default  # the rules' flag, written by the remux


def test_an_added_subtitle_is_named_with_the_subtitle_template_and_flagged_by_the_rules(b: SimpleNamespace) -> None:
    srt = SubtitleFile(Path("Show Name - S01E01.tr.forced.srt"), Language("tur"), forced=True)
    rules = [TrackRule(match=TrackMatch(kind=KindTest.SUBTITLE, languages=["tr"]), default=FlagShape.FIRST)]
    naming = replace(SUGGESTED, subtitle_track_template="{language}[ ({flags})]")
    item = b.item(b.video(0), b.audio(1, "English", "eng"), subtitles=(srt,))
    result = plan_mux(item, tracks=TracksOptions(rules=rules, add_paired=[PairedFile.of(srt)]), naming=naming)
    assert isinstance(result, MuxPlan)
    added = result.tracks[-1]
    assert added.planned.external == srt
    assert added.name == "Turkish (Forced)"
    assert added.language == Language("tur")
    assert added.flags == TrackFlags(default=True, forced=True)
    assert result.added == (srt,)


def test_the_suffix_and_a_non_matroska_source_name_the_output(b: SimpleNamespace) -> None:
    result = plan_mux(two_audio(b), mux=replace(ON, suffix=" [remux]"))
    assert isinstance(result, MuxPlan)
    assert result.output.name == "Show Name - S01E01 [remux].mkv"
    assert result.partial.name.startswith(".")  # out of the next scan
    assert result.partial.parent == result.source.parent


def test_the_keep_folder_and_suffix_must_be_file_names() -> None:
    assert check_names(MuxOptions()) == ()
    assert check_names(MuxOptions(original=Original.KEEP)) == ()
    assert check_names(MuxOptions(original=Original.KEEP, keep_folder="..")) == (NameField.KEEP_FOLDER,)
    assert check_names(MuxOptions(original=Original.KEEP, keep_folder="a/b")) == (NameField.KEEP_FOLDER,)
    assert check_names(MuxOptions(original=Original.KEEP, keep_folder="Kept.")) == (NameField.KEEP_FOLDER,)
    # Recycling reads no folder, so its name decides nothing.
    assert check_names(MuxOptions(keep_folder="")) == ()
    assert check_names(MuxOptions(suffix=" (new?)")) == (NameField.SUFFIX,)
