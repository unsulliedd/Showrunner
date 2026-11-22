"""Finished subtitles handed to the mux plan: each takes the place of what it was made of, a translation goes after the
file's tracks, and mkvmerge reads the kept results while the paired file is still the one moved away."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from showrunner.core.language import Language
from showrunner.core.media import MediaItem, SubtitleFile
from showrunner.core.naming import NamingOptions
from showrunner.core.track import TrackKind
from showrunner.stages.metadata import MetadataOptions, plan_metadata
from showrunner.stages.mux import MuxOptions, MuxPlan, plan_mux, verify
from showrunner.stages.mux import apply as module
from showrunner.stages.subtitles import RuleSetUse, SubtitlesOptions, SyncEngine, Wanted, plan_subtitles
from showrunner.stages.tracks import PairedFile, TracksOptions
from showrunner.tools.cleanit import RuleDef, RuleSet

TURKISH = SubtitleFile(Path("Show Name - S01E01.tr.srt"), Language("tur"))
RESULTS = Path("results")
SETS = {"Lyrics": RuleSet("Lyrics", (RuleDef(name="rule", patterns=("x",)),))}


def item(b: SimpleNamespace) -> MediaItem:
    return b.item(b.video(0), b.audio(1), b.subtitle(2), subtitles=(TURKISH,))


def planned(item: MediaItem, subtitles: SubtitlesOptions, tracks: TracksOptions) -> MuxPlan | None:
    work = plan_subtitles(item, subtitles, tracks, rule_sets=SETS)
    finished = [(f, RESULTS / f"{f.source.value}.{f.format}") for f in work.finished]
    result = plan_mux(item, MuxOptions(), tracks, MetadataOptions(), NamingOptions(), finished=finished)
    assert result is None or isinstance(result, MuxPlan)
    return result


def test_a_synced_paired_file_goes_in_as_its_result_and_is_still_moved_away(b: SimpleNamespace) -> None:
    tracks = TracksOptions(add_paired=[PairedFile.of(TURKISH)])
    plan = planned(item(b), SubtitlesOptions(sync=SyncEngine.FFSUBSYNC), tracks)
    assert plan is not None
    assert [t.content for t in plan.tracks] == [None, None, None, RESULTS / "paired.srt"]
    assert plan.added == (TURKISH,)
    spec = module._merge_spec(plan, Path("out.mkv"))
    assert spec.sources == (plan.source, RESULTS / "paired.srt")
    assert [(t.source, t.track_id) for t in spec.tracks] == [(0, 0), (0, 1), (0, 2), (1, 0)]


def test_only_subtitles_ask_for_a_new_file_and_a_translation_gets_a_track_of_its_own(b: SimpleNamespace) -> None:
    subtitles = SubtitlesOptions(languages={"de": Wanted.WANTED})
    assert planned(item(b), SubtitlesOptions(), TracksOptions()) is None
    plan = planned(item(b), subtitles, TracksOptions())
    assert plan is not None
    german = plan.tracks[-1]
    # Below the paired file's stand-in (-1), so no two tracks share an id.
    assert (german.planned.track.id, german.planned.track.kind, german.language) == (
        -2,
        TrackKind.SUBTITLE,
        Language("deu"),
    )
    assert (german.content, german.planned.external, plan.added) == (RESULTS / "translation.srt", None, ())
    assert module._merge_spec(plan, Path("out.mkv")).sources == (plan.source, RESULTS / "translation.srt")
    # The header goes into the remux, not to mkvpropedit.
    header = plan_metadata(item(b), MetadataOptions(), NamingOptions(), TracksOptions(), remux=True)
    assert header.needs_remux


def test_a_cleaned_embedded_track_takes_its_own_place(b: SimpleNamespace) -> None:
    turkish = b.subtitle(3, language="tur")
    video = b.item(b.video(0), b.audio(1), b.subtitle(2), turkish)
    subtitles = SubtitlesOptions(languages={"tr": Wanted.WANTED}, cleanup={"Lyrics": RuleSetUse.USED})
    plan = planned(video, subtitles, TracksOptions())
    assert plan is not None
    assert [t.content for t in plan.tracks] == [None, None, None, RESULTS / "embedded.srt"]
    spec = module._merge_spec(plan, Path("out.mkv"))
    assert [(t.source, t.track_id) for t in spec.tracks][-1] == (1, 0)


def test_the_check_holds_a_finished_subtitle_to_everything_but_its_codec(b: SimpleNamespace) -> None:
    turkish = b.subtitle(3, language="tur")
    video = b.item(b.video(0), b.audio(1), b.subtitle(2), turkish)
    subtitles = SubtitlesOptions(languages={"tr": Wanted.WANTED}, cleanup={"Lyrics": RuleSetUse.USED})
    plan = planned(video, subtitles, TracksOptions())
    assert plan is not None
    # mkvmerge reads the result as another format than the track had.
    cleaned = replace(turkish, codec="S_TEXT/ASS")
    after = replace(video.file, tracks=(b.video(0), b.audio(1), b.subtitle(2), cleaned))
    assert verify(plan, after) == ()
    renamed = replace(cleaned, name="Other")
    assert [p.what for p in verify(plan, replace(after, tracks=(*after.tracks[:3], renamed)))] == ["name"]
