from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar

from showrunner.app.jobs.groups import ChangeGroup
from showrunner.app.jobs.preview import FileOutcome, preview
from showrunner.app.jobs.stages import (
    RECHECK,
    MetadataStage,
    PlanState,
    Resumed,
    StagePlan,
    StepResult,
    TracksStage,
    pipeline,
)
from showrunner.app.profiles.profile import Profile
from showrunner.core.language import Language
from showrunner.core.media import MediaFile, MediaItem, Movie
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackKind, VideoProperties
from showrunner.stages.metadata import MetadataPlan
from showrunner.stages.tracks import FlagShape, KindTest, TrackMatch, TrackRule, TracksOptions, Verdict
from showrunner.tools.probe import Programs

STAGES = (TracksStage(), MetadataStage(Path("mkvpropedit"), Programs()))


@dataclass(frozen=True)
class Mux:
    """Stands in for a stage that writes a new file."""

    id: ClassVar[str] = "metadata"
    remuxes: ClassVar[bool] = True

    def plan(self, item: MediaItem, profile: Profile) -> StagePlan:
        return StagePlan(self.id, PlanState.CHANGES, writes=True)

    def apply(self, plan: StagePlan, cancel: threading.Event | None, progress: object = None) -> StepResult:
        raise AssertionError("a preview applies nothing")

    def resume(self, plan: StagePlan, before: object, cancel: threading.Event | None) -> Resumed:
        return RECHECK


def movie(tmp_path: Path, name: str = "Movie Title (2016).mkv") -> MediaItem:
    path = tmp_path / name
    path.write_bytes(b"matroska")
    tracks = (
        Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080, 23.976)),
        Track(1, TrackKind.AUDIO, "A_AC3", Language("eng"), audio=AudioProperties(6)),
        Track(2, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), subtitle=SubtitleProperties()),
    )
    return MediaItem(Movie("Movie Title", 2016), MediaFile(path, "matroska", tracks=tracks))


def with_rule(profile: Profile, kind: KindTest) -> Profile:
    rule = TrackRule(match=TrackMatch(kind=kind), verdict=Verdict.DROP)
    return profile.with_options("tracks", TracksOptions(rules=[rule]))


NO_NAMES = dict.fromkeys(
    ("title_template", "video_track_template", "audio_track_template", "subtitle_track_template"), ""
)


def naming(profile: Profile, **templates: str) -> Profile:
    return profile.with_options("naming", replace(profile.for_stage("naming"), **templates))


def test_header_changes_are_planned_and_written_by_metadata(tmp_path: Path, profile: Profile) -> None:
    result = preview([movie(tmp_path)], profile, STAGES)
    (file,) = result.files
    assert file.outcome is FileOutcome.CHANGES
    tracks = file.plan_for("tracks")
    assert tracks is not None
    assert tracks.state is PlanState.UNCHANGED  # the default profile has no rules
    metadata = file.plan_for("metadata")
    assert metadata is not None
    assert metadata.writes
    assert isinstance(metadata.plan, MetadataPlan)
    assert file.writes == (metadata,)


def test_a_file_with_nothing_to_change_is_unchanged(tmp_path: Path, profile: Profile) -> None:
    quiet = naming(profile, **NO_NAMES)
    (file,) = preview([movie(tmp_path)], quiet, STAGES).files
    assert file.outcome is FileOutcome.UNCHANGED
    assert file.writes == ()


def test_a_dropped_track_without_a_remux_writes_nothing(tmp_path: Path, profile: Profile) -> None:
    (file,) = preview([movie(tmp_path)], with_rule(profile, KindTest.SUBTITLE), STAGES).files
    assert file.outcome is FileOutcome.NEEDS_REMUX
    tracks = file.plan_for("tracks")
    assert tracks is not None
    assert tracks.state is PlanState.CHANGES
    assert tracks.needs_remux
    assert file.writes == ()


def test_a_stage_that_remuxes_carries_a_dropped_track(tmp_path: Path, profile: Profile) -> None:
    stages = (TracksStage(), Mux())
    (file,) = preview([movie(tmp_path)], with_rule(profile, KindTest.SUBTITLE), stages).files
    assert file.outcome is FileOutcome.CHANGES
    assert [plan.stage for plan in file.writes] == ["metadata"]


def test_rules_that_leave_no_audio_refuse_the_file(tmp_path: Path, profile: Profile) -> None:
    (file,) = preview([movie(tmp_path)], with_rule(profile, KindTest.AUDIO), STAGES).files
    assert file.outcome is FileOutcome.REFUSED
    tracks, metadata = file.plan_for("tracks"), file.plan_for("metadata")
    assert tracks is not None
    assert tracks.state is PlanState.REFUSED
    # The other stages still apply to the file, with its tracks as they are.
    assert file.writes == (metadata,)


def test_flags_that_no_stage_writes_are_named_as_such(tmp_path: Path, profile: Profile) -> None:
    rule = TrackRule(match=TrackMatch(kind=KindTest.AUDIO), default=FlagShape.FIRST)
    flags_only = profile.with_options("tracks", TracksOptions(rules=[rule]))
    # Without mkvpropedit there is no Metadata stage to write them.
    (file,) = preview([movie(tmp_path)], flags_only, (TracksStage(),)).files
    assert file.outcome is FileOutcome.UNWRITTEN
    assert file.writes == ()
    (written,) = preview([movie(tmp_path)], flags_only, STAGES).files
    assert written.outcome is FileOutcome.CHANGES


def test_a_blocked_stage_is_planned_for_no_file_and_seen_as_off(tmp_path: Path, profile: Profile) -> None:
    broken = with_rule(profile, KindTest.SUBTITLE)
    result = preview([movie(tmp_path)], broken, STAGES, blocked={"tracks"})
    (file,) = result.files
    tracks = file.plan_for("tracks")
    assert tracks is not None
    assert tracks.state is PlanState.BLOCKED
    # Metadata plans as if there were no rules: no remux is asked for, the header edits go ahead.
    assert file.outcome is FileOutcome.CHANGES
    assert result.profiles[result.options_key].for_stage("tracks").rules == []


def test_a_file_that_cannot_be_read_is_missing(tmp_path: Path, profile: Profile) -> None:
    item = movie(tmp_path)
    item.file.path.unlink()
    (file,) = preview([item], profile, STAGES).files
    assert file.outcome is FileOutcome.MISSING
    assert file.stamp is None
    assert file.error


def test_a_finished_file_is_still_planned(tmp_path: Path, profile: Profile) -> None:
    item = movie(tmp_path)
    seen: list[tuple[str, str]] = []

    def finished(content_hash: str, key: str) -> bool:
        seen.append((content_hash, key))
        return True

    result = preview([item], profile, STAGES, finished=finished)
    (file,) = result.files
    assert file.finished_before
    # The title comes from the file name, so a finished file that was renamed has changes again.
    assert file.outcome is FileOutcome.CHANGES
    assert seen == [(file.stamp.content_hash, result.options_key)]  # type: ignore[union-attr]
    assert not preview([item], profile, STAGES).files[0].finished_before


def test_the_options_key_follows_options_stages_and_blocks(profile: Profile) -> None:
    key = preview([], profile, STAGES).options_key
    assert preview([], profile, STAGES).options_key == key
    assert preview([], replace(profile, name="Other"), STAGES).options_key == key
    assert preview([], naming(profile, title_template=""), STAGES).options_key != key
    assert preview([], profile, STAGES[:1]).options_key != key
    assert preview([], profile, STAGES, blocked={"tracks"}).options_key != key
    assert preview([], profile, STAGES, left_out={ChangeGroup.NAMES}).options_key != key
    sourced = pipeline(Programs(), Path("mkvpropedit"), source="BluRay")
    assert preview([], profile, sourced).options_key != key
    assert preview([], profile, STAGES).is_current(profile, STAGES)
    assert not preview([], profile, STAGES).is_current(profile, STAGES, {"metadata"})
    assert not preview([], profile, STAGES).is_current(profile, STAGES, left_out={ChangeGroup.TRACKS})


def test_the_pipeline_leaves_out_a_stage_without_its_program() -> None:
    assert [s.id for s in pipeline(Programs(), None)] == ["tracks"]
    assert [s.id for s in pipeline(Programs(), Path("mkvpropedit"))] == ["tracks", "metadata"]


def test_an_unstamped_preview_reads_no_file(tmp_path: Path, profile: Profile) -> None:
    item = movie(tmp_path)
    item.file.path.unlink()
    result = preview([item], with_rule(profile, KindTest.SUBTITLE), STAGES, finished=lambda *_: True, stamped=False)
    (file,) = result.files
    assert (file.stamp, file.finished_before) == (None, False)
    assert file.outcome is FileOutcome.NEEDS_REMUX
    assert result.options_key == preview([], with_rule(profile, KindTest.SUBTITLE), STAGES).options_key
