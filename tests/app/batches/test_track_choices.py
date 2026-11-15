from __future__ import annotations

from pathlib import Path

from showrunner.app.batches.choices import NO_CHOICE, TrackChoice, TrackSignature, add_paired, choice_of, choose
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackFlags, TrackKind, VideoProperties
from showrunner.stages.tracks import (
    KindTest,
    PairedFile,
    TrackMatch,
    TrackPlan,
    TrackRule,
    TracksOptions,
    Verdict,
    plan_tracks,
)

VIDEO = Track(0, TrackKind.VIDEO, "V_MPEGH/ISO/HEVC", video=VideoProperties(1920, 1080, 23.976))
ENGLISH = Track(
    1, TrackKind.AUDIO, "A_AC3", Language("eng"), "English", TrackFlags(default=True), audio=AudioProperties(6)
)
# Near misses of ENGLISH: another name, no name, another codec and channels, another language.
COMMENTARY = Track(2, TrackKind.AUDIO, "A_AC3", Language("eng"), "English Commentary", audio=AudioProperties(6))
UNNAMED = Track(3, TrackKind.AUDIO, "A_AC3", Language("eng"), audio=AudioProperties(6))
STEREO = Track(4, TrackKind.AUDIO, "A_AAC", Language("eng"), "English", audio=AudioProperties(2))
TURKISH = Track(5, TrackKind.AUDIO, "A_AC3", Language("tur"), "English", audio=AudioProperties(6))
SUBTITLE = Track(6, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("tur"), "Turkish", subtitle=SubtitleProperties())
OTHER_SUBTITLE = Track(7, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), "English", subtitle=SubtitleProperties())


def episode(*tracks: Track) -> MediaItem:
    tracks = tracks or (VIDEO, ENGLISH, COMMENTARY, UNNAMED, STEREO, TURKISH, SUBTITLE, OTHER_SUBTITLE)
    return MediaItem(Episode("Show Name", 1, 1), MediaFile(Path("Show Name - S01E01.mkv"), "matroska", tracks=tracks))


def plan(options: TracksOptions, item: MediaItem | None = None) -> TrackPlan:
    result = plan_tracks(item or episode(), options)
    assert isinstance(result, TrackPlan)
    return result


def dropped(options: TracksOptions) -> list[int]:
    return [d.track.id for d in plan(options).dropped]


def flagged(options: TracksOptions, flag: str, item: MediaItem | None = None) -> list[int]:
    return [k.track.id for k in plan(options, item).kept if getattr(k.flags, flag)]


def test_dropping_a_signature_drops_exactly_those_tracks() -> None:
    options = choose(TracksOptions(), TrackSignature.of(ENGLISH), TrackChoice(Verdict.DROP))
    assert dropped(options) == [ENGLISH.id]
    (rule,) = options.rules
    assert rule.from_choice
    assert rule.verdict is Verdict.DROP


def test_the_signature_of_an_unnamed_track_leaves_named_ones_alone() -> None:
    assert dropped(choose(TracksOptions(), TrackSignature.of(UNNAMED), TrackChoice(Verdict.DROP))) == [UNNAMED.id]


def test_a_keep_choice_wins_over_a_hand_written_rule_that_drops_it() -> None:
    drop_english = TrackRule(label="Drop English audio", match=TrackMatch(languages=["en"]), verdict=Verdict.DROP)
    written = TracksOptions(rules=[drop_english])
    options = choose(written, TrackSignature.of(ENGLISH), TrackChoice(Verdict.KEEP))
    assert ENGLISH.id not in dropped(options)
    assert COMMENTARY.id in dropped(options)  # the hand-written rule still decides the rest
    assert options.rules[1] == drop_english  # and is not edited


def test_default_goes_to_the_chosen_signature_and_leaves_the_others_of_its_kind() -> None:
    options = choose(TracksOptions(), TrackSignature.of(TURKISH), TrackChoice(default=True))
    assert flagged(options, "default") == [TURKISH.id]
    assert dropped(options) == []


def test_a_second_default_is_the_fallback_of_the_first() -> None:
    options = choose(TracksOptions(), TrackSignature.of(TURKISH), TrackChoice(default=True))
    options = choose(options, TrackSignature.of(STEREO), TrackChoice(default=True))
    assert flagged(options, "default") == [TURKISH.id]
    without_turkish = episode(VIDEO, ENGLISH, STEREO)
    assert flagged(options, "default", without_turkish) == [STEREO.id]


def test_forced_goes_to_the_chosen_subtitle() -> None:
    options = choose(TracksOptions(), TrackSignature.of(SUBTITLE), TrackChoice(forced=True))
    assert flagged(options, "forced") == [SUBTITLE.id]


def test_a_new_choice_changes_the_old_one_in_its_place() -> None:
    hand = TrackRule(match=TrackMatch(kind=KindTest.SUBTITLE), verdict=Verdict.KEEP)
    options = choose(TracksOptions(rules=[hand]), TrackSignature.of(ENGLISH), TrackChoice(Verdict.KEEP))
    options = choose(options, TrackSignature.of(SUBTITLE), TrackChoice(forced=True))
    options = choose(options, TrackSignature.of(ENGLISH), TrackChoice(Verdict.DROP, default=True))
    assert [r.from_choice for r in options.rules] == [True, True, False]
    assert choice_of(options, TrackSignature.of(ENGLISH)) == TrackChoice(Verdict.DROP)  # a dropped track takes no flag
    assert choice_of(options, TrackSignature.of(SUBTITLE)) == TrackChoice(forced=True)
    assert dropped(options) == [ENGLISH.id]


def test_undoing_a_choice_removes_its_rule_and_nothing_else() -> None:
    hand = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["tr"]), verdict=Verdict.DROP)
    written = TracksOptions(rules=[hand])
    options = choose(written, TrackSignature.of(ENGLISH), TrackChoice(Verdict.DROP))
    assert choose(options, TrackSignature.of(ENGLISH), NO_CHOICE) == written
    assert choice_of(written, TrackSignature.of(ENGLISH)) == NO_CHOICE
    assert choose(written, TrackSignature.of(ENGLISH), NO_CHOICE) == written


def test_a_hand_written_rule_with_the_same_match_is_not_taken_for_a_choice() -> None:
    same = TrackRule(match=TrackSignature.of(ENGLISH).match(), verdict=Verdict.DROP)
    written = TracksOptions(rules=[same])
    assert choice_of(written, TrackSignature.of(ENGLISH)) == NO_CHOICE
    options = choose(written, TrackSignature.of(ENGLISH), TrackChoice(Verdict.KEEP))
    assert options.rules[1] == same
    assert dropped(options) == []


def test_a_track_without_a_language_has_its_own_signature() -> None:
    untagged = Track(8, TrackKind.AUDIO, "A_AC3", None, "English", audio=AudioProperties(6))
    options = choose(TracksOptions(), TrackSignature.of(untagged), TrackChoice(Verdict.DROP))
    assert TrackSignature.of(untagged).language == "und"
    assert [d.track.id for d in plan(options, episode(VIDEO, ENGLISH, untagged)).dropped] == [untagged.id]


PAIRED = MediaItem(
    Episode("Show Name", 1, 1),
    MediaFile(Path("Show Name - S01E01.mkv"), "matroska", tracks=(VIDEO, ENGLISH, TURKISH)),
    (SubtitleFile(Path("Show Name - S01E01.tr.srt"), Language("tur")),),
)


def test_a_star_alone_never_adds_a_paired_file() -> None:
    options = choose(TracksOptions(), TrackSignature.of(TURKISH), TrackChoice(default=True))
    assert not plan(options, PAIRED).needs_remux


def test_a_paired_file_is_added_by_its_own_choice_and_then_chosen_like_a_track() -> None:
    srt = PairedFile.of(PAIRED.subtitles[0])
    options = add_paired(TracksOptions(), srt, True)
    assert add_paired(options, srt, True) == options  # chosen once
    added = plan(options, PAIRED)
    assert added.needs_remux
    stand_in = added.kept[-1].track
    assert added.kept[-1].external == PAIRED.subtitles[0]
    starred = choose(options, TrackSignature.of(stand_in), TrackChoice(default=True))
    assert flagged(starred, "default", PAIRED) == [ENGLISH.id, stand_in.id]
    assert add_paired(options, srt, False) == TracksOptions()
