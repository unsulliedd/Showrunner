from __future__ import annotations

from types import SimpleNamespace

import pytest

from showrunner.core.track import ObjectAudio
from showrunner.stages.tracks import FlagTest, KindTest, TrackMatch, matches


def test_an_empty_match_fits_every_track(b: SimpleNamespace) -> None:
    assert matches(TrackMatch(), b.video())
    assert matches(TrackMatch(), b.audio(1))


def test_kind(b: SimpleNamespace) -> None:
    assert matches(TrackMatch(kind=KindTest.AUDIO), b.audio(1))
    assert not matches(TrackMatch(kind=KindTest.AUDIO), b.subtitle(2))


def test_language_by_either_code_form(b: SimpleNamespace) -> None:
    track = b.audio(1, language=b.tr)
    assert matches(TrackMatch(languages=["tr"]), track)
    assert matches(TrackMatch(languages=["tur"]), track)
    assert matches(TrackMatch(languages=["en", "tr"]), track)
    assert not matches(TrackMatch(languages=["en"]), track)


def test_a_tag_without_region_fits_every_region_but_a_region_must_agree(b: SimpleNamespace) -> None:
    track = b.audio(1, language=b.pt_br)
    assert matches(TrackMatch(languages=["pt"]), track)
    assert matches(TrackMatch(languages=["pt-BR"]), track)
    assert not matches(TrackMatch(languages=["pt-PT"]), track)
    assert not matches(TrackMatch(languages=["pt-BR"]), b.audio(2, language=b.en))


def test_no_language(b: SimpleNamespace) -> None:
    undetermined = TrackMatch(languages=["und"])
    assert matches(undetermined, b.audio(1))
    assert not matches(undetermined, b.audio(2, language=b.en))
    assert matches(TrackMatch(languages=["en", "und"]), b.audio(3))
    assert not matches(TrackMatch(languages=["en"]), b.audio(4))


def test_text_that_is_not_a_language_fits_nothing(b: SimpleNamespace) -> None:
    assert not matches(TrackMatch(languages=["not a language"]), b.audio(1, language=b.en))
    assert not matches(TrackMatch(languages=["not a language"]), b.audio(2))


def test_codec_by_id_or_display_name_in_any_case(b: SimpleNamespace) -> None:
    track = b.audio(1, "A_EAC3")
    assert matches(TrackMatch(codecs=["A_EAC3"]), track)
    assert matches(TrackMatch(codecs=["dolby digital plus"]), track)
    assert not matches(TrackMatch(codecs=["Dolby Digital"]), track)
    assert not matches(TrackMatch(codecs=["AAC", "DTS"]), track)


def test_a_plain_codec_name_also_fits_the_object_audio_variant(b: SimpleNamespace) -> None:
    track = b.audio(1, "A_DTS", object_audio=ObjectAudio.DTS_X)
    assert matches(TrackMatch(codecs=["DTS"]), track)
    assert matches(TrackMatch(codecs=["DTS:X"]), track)
    assert not matches(TrackMatch(codecs=["DTS:X"]), b.audio(2, "A_DTS"))


@pytest.mark.parametrize(
    ("low", "high", "channels", "expected"),
    [
        (6, 6, 6, True),
        (6, 6, 8, False),
        (6, 0, 8, True),
        (6, 0, 2, False),
        (0, 2, 2, True),
        (0, 2, 6, False),
        (3, 6, 6, True),
        (3, 6, 7, False),
    ],
)
def test_channels_exact_or_range(b: SimpleNamespace, low: int, high: int, channels: int, expected: bool) -> None:
    assert matches(TrackMatch(min_channels=low, max_channels=high), b.audio(1, channels=channels)) is expected


def test_unknown_channels_and_other_kinds_fit_no_channel_test(b: SimpleNamespace) -> None:
    assert not matches(TrackMatch(min_channels=1), b.audio(1, channels=None))
    assert not matches(TrackMatch(min_channels=1), b.subtitle(2))


def test_flags_set_and_unset(b: SimpleNamespace) -> None:
    forced = b.subtitle(1, forced=True)
    plain = b.subtitle(2)
    assert matches(TrackMatch(forced=FlagTest.SET), forced)
    assert not matches(TrackMatch(forced=FlagTest.SET), plain)
    assert matches(TrackMatch(forced=FlagTest.UNSET), plain)
    assert not matches(TrackMatch(forced=FlagTest.UNSET), forced)


@pytest.mark.parametrize("flag", ["default", "forced", "hearing_impaired", "visual_impaired", "commentary", "original"])
def test_every_flag_can_be_tested(b: SimpleNamespace, flag: str) -> None:
    assert matches(TrackMatch(**{flag: FlagTest.SET}), b.audio(1, **{flag: True}))
    assert not matches(TrackMatch(**{flag: FlagTest.SET}), b.audio(2))


def test_all_tests_must_fit(b: SimpleNamespace) -> None:
    match = TrackMatch(kind=KindTest.AUDIO, languages=["en"], codecs=["DTS"], hearing_impaired=FlagTest.UNSET)
    assert matches(match, b.audio(1, "A_DTS", b.en))
    assert not matches(match, b.audio(2, "A_DTS", b.tr))
    assert not matches(match, b.audio(3, "A_DTS", b.en, hearing_impaired=True))


def test_name_text_is_found_anywhere_in_any_case(b: SimpleNamespace) -> None:
    track = b.audio(1, name="Director's Commentary")
    assert matches(TrackMatch(name="commentary"), track)
    assert not matches(TrackMatch(name="^commentary"), track)
    assert not matches(TrackMatch(name="commentary"), b.audio(2, name="Main"))


def test_name_regular_expression(b: SimpleNamespace) -> None:
    track = b.subtitle(1, name="English [SDH]")
    assert matches(TrackMatch(name=r"\[(sdh|cc)\]$", name_is_regex=True), track)
    assert not matches(TrackMatch(name=r"^sdh", name_is_regex=True), track)


def test_an_invalid_regular_expression_fits_nothing(b: SimpleNamespace) -> None:
    assert not matches(TrackMatch(name="(", name_is_regex=True), b.audio(1, name="("))
