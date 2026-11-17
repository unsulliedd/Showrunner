"""The order of the tracks in the new file: `TracksOptions.order` and how it meets the `first` flag rules."""

from __future__ import annotations

from types import SimpleNamespace

from showrunner.core.language import Language
from showrunner.core.track import TrackKind
from showrunner.stages.tracks import (
    FlagShape,
    KindTest,
    PairedFile,
    PlanRefused,
    TrackMatch,
    TrackPlan,
    TrackRule,
    TracksOptions,
    Verdict,
    order_places,
    plan_tracks,
)

DE, FR = Language.parse("de"), Language.parse("fr")


def planned(result: TrackPlan | PlanRefused) -> TrackPlan:
    assert isinstance(result, TrackPlan)
    return result


def kept_ids(plan: TrackPlan) -> list[int]:
    return [k.track.id for k in plan.kept]


def audio_in(*languages: str) -> list[TrackMatch]:
    return [TrackMatch(kind=KindTest.AUDIO, languages=[language]) for language in languages]


def test_an_empty_order_keeps_the_file_order_and_plans_no_remux(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr), b.subtitle(3, b.en))
    plan = planned(plan_tracks(media, TracksOptions()))
    assert kept_ids(plan) == [0, 1, 2, 3]
    assert not plan.reordered
    assert not plan.needs_remux


def test_the_order_alone_plans_a_remux(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr), b.subtitle(3, b.en))
    plan = planned(plan_tracks(media, TracksOptions(order=audio_in("tr", "en"))))
    assert kept_ids(plan) == [0, 2, 1, 3]
    assert plan.reordered
    assert plan.needs_remux
    assert plan.dropped == ()


def test_an_order_equal_to_the_file_order_changes_nothing(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=b.tr), b.subtitle(3, b.en))
    plan = planned(plan_tracks(media, TracksOptions(order=audio_in("en", "tr"))))
    assert kept_ids(plan) == [0, 1, 2, 3]
    assert not plan.reordered
    assert not plan.needs_remux


def test_tracks_the_order_does_not_name_follow_the_named_ones_in_file_order(b: SimpleNamespace) -> None:
    media = b.item(
        b.video(),
        b.audio(1, language=b.en),
        b.audio(2, language=DE),
        b.audio(3, language=b.tr),
        b.audio(4, language=FR),
    )
    plan = planned(plan_tracks(media, TracksOptions(order=audio_in("tr", "de"))))
    assert kept_ids(plan) == [0, 3, 2, 1, 4]


def test_a_file_without_a_named_track_skips_it(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=DE))
    plan = planned(plan_tracks(media, TracksOptions(order=audio_in("tr", "de", "en"))))
    assert kept_ids(plan) == [0, 2, 1]


def test_each_kind_keeps_its_places_whatever_the_order_names(b: SimpleNamespace) -> None:
    """Video stays first, and a subtitle never takes an audio track's place, even with an entry that fits any kind."""
    media = b.item(b.video(), b.audio(1, language=b.en), b.subtitle(2, b.tr), b.audio(3, language=b.tr))
    order = [TrackMatch(languages=["tr"])]
    plan = planned(plan_tracks(media, TracksOptions(order=order)))
    assert kept_ids(plan) == [0, 3, 2, 1]
    assert [k.track.kind for k in plan.kept] == [TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.SUBTITLE, TrackKind.AUDIO]


def test_a_dropped_track_leaves_the_order_of_the_rest(b: SimpleNamespace) -> None:
    media = b.item(b.video(), b.audio(1, language=b.en), b.audio(2, language=DE), b.audio(3, language=b.tr))
    rules = [TrackRule(match=TrackMatch(languages=["de"]), verdict=Verdict.DROP)]
    plan = planned(plan_tracks(media, TracksOptions(rules=rules, order=audio_in("tr", "de", "en"))))
    assert kept_ids(plan) == [0, 3, 1]
    assert [d.track.id for d in plan.dropped] == [2]


def test_an_added_subtitle_file_can_go_ahead_of_the_embedded_subtitles(b: SimpleNamespace) -> None:
    paired = b.srt(b.tr)
    media = b.item(b.video(), b.audio(1, language=b.en), b.subtitle(2, b.en), subtitles=(paired,))
    order = [TrackMatch(kind=KindTest.SUBTITLE, languages=["tr"])]
    plan = planned(plan_tracks(media, TracksOptions(add_paired=[PairedFile.of(paired)], order=order)))
    assert [k.external for k in plan.kept] == [None, None, paired, None]
    assert kept_ids(plan) == [0, 1, -1, 2]
    assert plan.reordered


def test_a_first_rule_gives_the_flag_to_the_first_fitting_track_in_the_new_order(b: SimpleNamespace) -> None:
    """A `first` rule that fits two English tracks reads them in the new file's order."""
    media = b.item(
        b.video(),
        b.audio(1, "A_AC3", b.en, channels=6, default=True),
        b.audio(2, "A_AAC", b.en, channels=2),
    )
    rule = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["en"]), default=FlagShape.FIRST)
    in_file = planned(plan_tracks(media, TracksOptions(rules=[rule])))
    assert [k.flags.default for k in in_file.kept] == [False, True, False]
    stereo_first = [TrackMatch(kind=KindTest.AUDIO, min_channels=2, max_channels=2)]
    plan = planned(plan_tracks(media, TracksOptions(rules=[rule], order=stereo_first)))
    assert kept_ids(plan) == [0, 2, 1]
    assert [(k.track.id, k.flags.default) for k in plan.kept] == [(0, False), (2, True), (1, False)]


def test_order_places_sorts_each_kind_into_its_own_places() -> None:
    kinds = [TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.SUBTITLE, TrackKind.AUDIO, TrackKind.SUBTITLE]
    assert order_places(kinds, [9, 1, 1, 0, 0]) == [0, 3, 4, 1, 2]
    # Equal ranks keep their order.
    assert order_places(kinds, [0, 5, 5, 5, 5]) == [0, 1, 2, 3, 4]
