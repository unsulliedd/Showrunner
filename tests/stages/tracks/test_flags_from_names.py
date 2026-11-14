from __future__ import annotations

from types import SimpleNamespace

import pytest

from showrunner.core.media import MediaItem
from showrunner.core.track import Track, TrackFlags, TrackKind, flags_with_name
from showrunner.stages.tracks import (
    FlagTest,
    KindTest,
    TrackMatch,
    TrackPlan,
    TrackRule,
    TracksOptions,
    Verdict,
    plan_tracks,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Commentary by the director", TrackFlags(commentary=True)),
        ("Director's commentary", TrackFlags(commentary=True)),
        ("English (SDH)", TrackFlags(hearing_impaired=True)),
        ("English CC", TrackFlags(hearing_impaired=True)),
        ("English Forced", TrackFlags(forced=True)),
        ("Forced SDH", TrackFlags(forced=True, hearing_impaired=True)),
        # Words inside other words do not count: "AAC" holds "cc", "Unforced" holds "forced".
        ("AAC 2.0", TrackFlags()),
        ("Unforced take", TrackFlags()),
        ("", TrackFlags()),
    ],
)
def test_a_name_implies_flags(name: str, expected: TrackFlags) -> None:
    track = Track(1, TrackKind.AUDIO, "A_AAC", name=name)
    assert flags_with_name(track) == expected


def test_flags_the_file_sets_are_kept() -> None:
    track = Track(1, TrackKind.SUBTITLE, "S_TEXT/UTF8", name="English (SDH)", flags=TrackFlags(default=True))
    assert flags_with_name(track) == TrackFlags(default=True, hearing_impaired=True)


def drop_commentary(*, from_names: bool) -> TracksOptions:
    rule = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, commentary=FlagTest.SET), verdict=Verdict.DROP)
    return TracksOptions(enabled=True, rules=[rule], flags_from_names=from_names)


def test_a_rule_on_the_commentary_flag_catches_a_track_named_commentary(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, name="Main"), b.audio(2, name="Commentary by the creators"))
    plan = b_plan(item, drop_commentary(from_names=True))
    assert [d.track.id for d in plan.dropped] == [2]
    assert [k.track.id for k in plan.kept] == [0, 1]


def test_with_the_option_off_only_the_file_flag_counts(b: SimpleNamespace) -> None:
    item = b.item(b.video(0), b.audio(1, name="Main"), b.audio(2, name="Commentary by the creators"))
    plan = b_plan(item, drop_commentary(from_names=False))
    assert plan.dropped == ()


def test_a_flag_implied_by_a_name_is_not_written_as_a_change(b: SimpleNamespace) -> None:
    # Reading a flag from the name affects matching only; the plan does not claim to set it.
    rule = TrackRule(match=TrackMatch(kind=KindTest.AUDIO), verdict=Verdict.KEEP)
    item = b.item(b.video(0), b.audio(1, name="Commentary"))
    plan = b_plan(item, TracksOptions(enabled=True, rules=[rule]))
    assert all(k.flag_changes == () for k in plan.kept)


def b_plan(item: MediaItem, options: TracksOptions) -> TrackPlan:
    plan = plan_tracks(item, options)
    assert isinstance(plan, TrackPlan)
    return plan
