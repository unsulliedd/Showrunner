from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from showrunner.app.batches.choices import (
    NO_CHOICE,
    TrackChoice,
    TrackGroups,
    TrackSignature,
    add_paired,
    add_rule,
    choice_of,
    choose,
    in_order,
    move_rule,
    move_track,
    pause_rule,
    replace_rule,
    signature_of,
)
from showrunner.core.language import Language
from showrunner.core.media import Episode, MediaFile, MediaItem, SubtitleFile
from showrunner.core.track import AudioProperties, SubtitleProperties, Track, TrackFlags, TrackKind, VideoProperties
from showrunner.stages.tracks import (
    FlagTest,
    KindTest,
    PairedFile,
    SourceTest,
    TrackMatch,
    TrackPlan,
    TrackRule,
    TracksOptions,
    Verdict,
    matches,
    plan_tracks,
    stand_in,
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


# In the sample file ENGLISH and UNNAMED are alike but for the name, so their group is told apart by name.
GROUPS = TrackGroups.of([episode()], flags_from_names=True)
sig = GROUPS.signature


def plan(options: TracksOptions, item: MediaItem | None = None) -> TrackPlan:
    result = plan_tracks(item or episode(), options)
    assert isinstance(result, TrackPlan)
    return result


def dropped(options: TracksOptions) -> list[int]:
    return [d.track.id for d in plan(options).dropped]


def flagged(options: TracksOptions, flag: str, item: MediaItem | None = None) -> list[int]:
    return [k.track.id for k in plan(options, item).kept if getattr(k.flags, flag)]


def test_dropping_a_signature_drops_exactly_those_tracks() -> None:
    options = choose(TracksOptions(), sig(ENGLISH), TrackChoice(Verdict.DROP))
    assert dropped(options) == [ENGLISH.id]
    (rule,) = options.rules
    assert rule.from_choice
    assert rule.verdict is Verdict.DROP


def test_an_unnamed_track_told_apart_by_name_leaves_the_named_one_alone() -> None:
    assert dropped(choose(TracksOptions(), sig(UNNAMED), TrackChoice(Verdict.DROP))) == [UNNAMED.id]


def test_a_keep_choice_wins_over_a_hand_written_rule_that_drops_it() -> None:
    drop_english = TrackRule(label="Drop English audio", match=TrackMatch(languages=["en"]), verdict=Verdict.DROP)
    written = TracksOptions(rules=[drop_english])
    options = choose(written, sig(ENGLISH), TrackChoice(Verdict.KEEP))
    assert ENGLISH.id not in dropped(options)
    assert COMMENTARY.id in dropped(options)  # the hand-written rule still decides the rest
    assert options.rules[1] == drop_english  # and is not edited


def test_default_goes_to_the_chosen_signature_and_leaves_the_others_of_its_kind() -> None:
    options = choose(TracksOptions(), sig(TURKISH), TrackChoice(default=True))
    assert flagged(options, "default") == [TURKISH.id]
    assert dropped(options) == []


def test_a_second_default_is_the_fallback_of_the_first() -> None:
    options = choose(TracksOptions(), sig(TURKISH), TrackChoice(default=True))
    options = choose(options, sig(STEREO), TrackChoice(default=True))
    assert flagged(options, "default") == [TURKISH.id]
    without_turkish = episode(VIDEO, ENGLISH, STEREO)
    assert flagged(options, "default", without_turkish) == [STEREO.id]


def test_forced_goes_to_the_chosen_subtitle() -> None:
    options = choose(TracksOptions(), sig(SUBTITLE), TrackChoice(forced=True))
    assert flagged(options, "forced") == [SUBTITLE.id]


def test_a_new_choice_changes_the_old_one_in_its_place() -> None:
    hand = TrackRule(match=TrackMatch(kind=KindTest.SUBTITLE), verdict=Verdict.KEEP)
    options = choose(TracksOptions(rules=[hand]), sig(ENGLISH), TrackChoice(Verdict.KEEP))
    options = choose(options, sig(SUBTITLE), TrackChoice(forced=True))
    options = choose(options, sig(ENGLISH), TrackChoice(Verdict.DROP, default=True))
    assert [r.from_choice for r in options.rules] == [True, True, False]
    assert choice_of(options, sig(ENGLISH)) == TrackChoice(Verdict.DROP)  # a dropped track takes no flag
    assert choice_of(options, sig(SUBTITLE)) == TrackChoice(forced=True)
    assert dropped(options) == [ENGLISH.id]


def test_undoing_a_choice_removes_its_rule_and_nothing_else() -> None:
    hand = TrackRule(match=TrackMatch(kind=KindTest.AUDIO, languages=["tr"]), verdict=Verdict.DROP)
    written = TracksOptions(rules=[hand])
    options = choose(written, sig(ENGLISH), TrackChoice(Verdict.DROP))
    assert choose(options, sig(ENGLISH), NO_CHOICE) == written
    assert choice_of(written, sig(ENGLISH)) == NO_CHOICE
    assert choose(written, sig(ENGLISH), NO_CHOICE) == written


def test_a_hand_written_rule_with_the_same_match_is_not_taken_for_a_choice() -> None:
    same = TrackRule(match=sig(ENGLISH).match(), verdict=Verdict.DROP)
    written = TracksOptions(rules=[same])
    assert choice_of(written, sig(ENGLISH)) == NO_CHOICE
    options = choose(written, sig(ENGLISH), TrackChoice(Verdict.KEEP))
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
    options = choose(TracksOptions(), sig(TURKISH), TrackChoice(default=True))
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


def test_rules_move_and_pause_in_place() -> None:
    first, second, third = (TrackRule(label=name) for name in ("first", "second", "third"))
    options = TracksOptions(rules=[first, second, third])
    assert [r.label for r in move_rule(options, 0, 2).rules] == ["second", "third", "first"]
    assert [r.label for r in move_rule(options, 2, 0).rules] == ["third", "first", "second"]
    assert [r.label for r in move_rule(options, 1, 9).rules] == ["first", "third", "second"]
    paused = pause_rule(options, 1, True)
    assert [r.enabled for r in paused.rules] == [True, False, True]
    assert pause_rule(paused, 1, False) == options
    assert options.rules[1].enabled  # the old list is untouched


def test_a_written_rule_goes_last_and_an_edited_one_stays_in_place() -> None:
    turkish = sig(TURKISH)
    written = TrackRule(label="written")
    options = add_rule(TracksOptions(rules=[written]), written)
    assert [r.label for r in options.rules] == ["written", "written"]
    # A choice made afterwards still leads the list, ahead of the rules written by hand.
    chosen = choose(options, turkish, TrackChoice(Verdict.KEEP))
    assert [r.from_choice for r in chosen.rules] == [True, False, False]
    edited = replace_rule(chosen, 2, TrackRule(label="edited"))
    assert [r.label for r in edited.rules] == ["", "written", "edited"]
    assert chosen.rules[2].label == "written"  # the old list is untouched


def test_a_choice_rule_names_its_signature() -> None:
    signatures = [sig(ENGLISH), sig(TURKISH)]
    options = choose(TracksOptions(), signatures[1], TrackChoice(Verdict.DROP))
    assert signature_of(options.rules[0], signatures) == signatures[1]
    hand_written = replace(options.rules[0], from_choice=False)
    assert signature_of(hand_written, signatures) is None


def test_a_paused_choice_is_no_choice_until_chosen_again() -> None:
    turkish = sig(TURKISH)
    options = choose(TracksOptions(rules=[TrackRule(label="hand")]), turkish, TrackChoice(Verdict.KEEP, default=True))
    paused = pause_rule(options, 0, True)
    assert choice_of(paused, turkish) == NO_CHOICE
    again = choose(paused, turkish, TrackChoice(Verdict.KEEP, default=True))
    assert again == options  # the same rule in the same place, on again


def named_episode(number: int, *tracks: Track) -> MediaItem:
    """An episode whose tracks are named after it, as some releases do: "Show Name - 1x01 - Episode (English)"."""
    named = tuple(replace(t, name=f"Show Name - 1x{number:02d} - Episode ({t.name})") for t in tracks)
    path = Path(f"Show Name - S01E{number:02d}.mkv")
    return MediaItem(Episode("Show Name", 1, number), MediaFile(path, "matroska", tracks=named))


SDH = Track(8, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), "SDH", subtitle=SubtitleProperties())
FORCED = Track(
    9, TrackKind.SUBTITLE, "S_TEXT/UTF8", Language("eng"), "", TrackFlags(forced=True), subtitle=SubtitleProperties()
)
DESCRIBED = Track(
    10, TrackKind.AUDIO, "A_AC3", Language("eng"), "", TrackFlags(visual_impaired=True), audio=AudioProperties(6)
)
SEASON = [named_episode(n, VIDEO, ENGLISH, COMMENTARY, OTHER_SUBTITLE, SDH, FORCED, DESCRIBED) for n in (1, 2, 3)]


def every_track(item: MediaItem) -> list[Track]:
    """The file's tracks and the stand-ins of every paired file beside it, as a chip or column sees them."""
    return [*item.file.tracks, *(stand_in(s, i) for i, s in enumerate(item.subtitles))]


def members(groups: TrackGroups, items: list[MediaItem]) -> dict[TrackSignature, set[tuple[int, int]]]:
    found: dict[TrackSignature, set[tuple[int, int]]] = {}
    for n, item in enumerate(items):
        for track in every_track(item):
            found.setdefault(groups.signature(track), set()).add((n, track.id))
    return found


def test_tracks_named_per_episode_fall_in_one_group_by_what_they_are() -> None:
    groups = TrackGroups.of(SEASON, flags_from_names=True)
    found = members(groups, SEASON)
    assert len(found) == 7  # the video and one group per track, whatever the episode's name
    assert all(len(tracks) == 3 for tracks in found.values())
    commentary = groups.signature(SEASON[0].file.tracks[2])
    assert commentary.commentary
    assert commentary.name is None
    assert groups.signature(SEASON[0].file.tracks[4]).hearing_impaired
    assert groups.signature(SEASON[0].file.tracks[5]).forced
    assert groups.signature(SEASON[0].file.tracks[6]).visual_impaired


def test_without_flags_from_names_a_commentary_named_so_is_alike_and_told_apart_by_name() -> None:
    groups = TrackGroups.of(SEASON, flags_from_names=False)
    english, commentary = (groups.signature(t) for t in SEASON[0].file.tracks[1:3])
    assert english != commentary
    assert english.name == SEASON[0].file.tracks[1].name
    assert commentary.name == SEASON[0].file.tracks[2].name


def test_two_alike_tracks_in_one_file_split_their_group_by_name_in_every_file() -> None:
    second = replace(UNNAMED, id=11, name="Main")
    items = [named_episode(1, VIDEO, ENGLISH), episode(VIDEO, ENGLISH, second)]
    groups = TrackGroups.of(items, flags_from_names=True)
    assert {groups.signature(t).name for item in items for t in item.file.tracks[1:]} == {
        items[0].file.tracks[1].name,
        "English",
        "Main",
    }
    one = TrackGroups.of(items[:1], flags_from_names=True)
    assert one.signature(items[0].file.tracks[1]).name is None  # a batch without the pair keeps the group whole


def test_a_paired_file_and_its_embedded_twin_are_two_groups_by_where_they_come_from() -> None:
    for name in ("Turkish", ""):  # an unnamed twin too, which a split by name could not tell apart
        embedded = replace(SUBTITLE, name=name)
        item = replace(PAIRED, file=replace(PAIRED.file, tracks=(VIDEO, ENGLISH, embedded)))
        groups = TrackGroups.of([item], flags_from_names=True)
        twin = plan_tracks(item, add_paired(TracksOptions(), PairedFile.of(item.subtitles[0]), True))
        assert isinstance(twin, TrackPlan)
        inside, beside = groups.signature(embedded), groups.signature(twin.kept[-1].track)
        assert (inside.paired, beside.paired) == (False, True)
        assert inside.name is None
        assert beside.name is None  # added or not, no group needs the name
        assert inside.match().source is SourceTest.EMBEDDED
        assert beside.match().source is SourceTest.PAIRED


def test_a_season_with_a_paired_file_and_an_embedded_track_named_per_episode_has_one_group_each() -> None:
    turkish = replace(SUBTITLE, name="Turkish")
    season = [replace(named_episode(n, VIDEO, ENGLISH, turkish), subtitles=PAIRED.subtitles) for n in (1, 2, 3)]
    groups = TrackGroups.of(season, flags_from_names=True)
    found = members(groups, season)
    subtitles = [s for s in found if s.kind is TrackKind.SUBTITLE]
    assert len(subtitles) == 2
    assert all(s.name is None and len(found[s]) == 3 for s in subtitles)
    inside = next(s for s in subtitles if not s.paired)
    options = add_paired(
        choose(TracksOptions(), inside, TrackChoice(Verdict.DROP)), PairedFile.of(PAIRED.subtitles[0]), True
    )
    for item in season:  # dropping the embedded group keeps the paired file
        result = plan(options, item)
        assert [d.track.id for d in result.dropped] == [SUBTITLE.id]
        assert result.kept[-1].track.id == -1


def test_an_audio_choice_has_no_source_test() -> None:
    (audio,) = choose(TracksOptions(), sig(ENGLISH), TrackChoice(Verdict.DROP)).rules
    assert audio.match.source is SourceTest.ANY  # audio comes only from inside the file


def test_a_subtitle_choice_stored_before_the_source_test_is_still_its_chip_s() -> None:
    turkish = sig(SUBTITLE)
    old = TrackRule(match=replace(turkish.match(), source=SourceTest.ANY), verdict=Verdict.KEEP, from_choice=True)
    options = TracksOptions(rules=[old, TrackRule(label="hand")])
    assert choice_of(options, turkish) == TrackChoice(Verdict.KEEP)
    assert signature_of(old, [turkish]) == turkish
    dropping = choose(options, turkish, TrackChoice(Verdict.DROP))
    assert [r.label for r in dropping.rules] == ["", "hand"]  # rewritten in its place, not added below it
    assert dropping.rules[0].match == turkish.match()
    assert dropped(dropping) == [SUBTITLE.id]


def test_each_group_s_rule_fits_exactly_its_own_tracks() -> None:
    split = episode(VIDEO, ENGLISH, COMMENTARY, UNNAMED, STEREO, TURKISH, SUBTITLE, OTHER_SUBTITLE, SDH, FORCED)
    # A Turkish SubRip track in one file, a Turkish .srt file beside another: two columns, apart by where they come
    # from.
    embedded_here = replace(PAIRED, file=replace(PAIRED.file, tracks=(VIDEO, ENGLISH, SUBTITLE)), subtitles=())
    for items in (SEASON, [*SEASON, split], [split], [embedded_here, PAIRED], [PAIRED, *SEASON]):
        for from_names in (True, False):
            groups = TrackGroups.of(items, flags_from_names=from_names)
            for signature, tracks in members(groups, items).items():
                fits = {
                    (n, t.id)
                    for n, item in enumerate(items)
                    for t in every_track(item)
                    if matches(signature.match(), t, flags_from_name=from_names)
                }
                assert fits == tracks, signature
                assert len({track_id < 0 for _, track_id in tracks}) == 1, signature  # never a track and a file


def test_a_choice_writes_flag_tests_and_no_name_unless_its_group_needs_one() -> None:
    groups = TrackGroups.of(SEASON, flags_from_names=True)
    (rule,) = choose(TracksOptions(), groups.signature(SEASON[0].file.tracks[2]), TrackChoice(Verdict.DROP)).rules
    assert rule.match.name == ""
    assert rule.match.commentary is FlagTest.SET
    assert (rule.match.hearing_impaired, rule.match.forced, rule.match.visual_impaired) == (FlagTest.UNSET,) * 3
    assert [d.track.id for item in SEASON for d in plan(TracksOptions(rules=[rule]), item).dropped] == [2, 2, 2]
    (named,) = choose(TracksOptions(), sig(UNNAMED), TrackChoice(Verdict.DROP)).rules
    assert named.match.name == "^$"
    assert named.match.name_is_regex


def test_a_choice_rule_from_a_name_signature_is_an_ordinary_rule_now() -> None:
    old = TrackMatch(
        kind=KindTest.AUDIO, languages=["en"], codecs=["A_AC3"], min_channels=6, max_channels=6, name="^English$"
    )
    options = TracksOptions(
        rules=[TrackRule(match=replace(old, name_is_regex=True), verdict=Verdict.DROP, from_choice=True)]
    )
    groups = TrackGroups.of([episode(VIDEO, ENGLISH)], flags_from_names=True)
    english = groups.signature(ENGLISH)
    assert choice_of(options, english) == NO_CHOICE
    assert signature_of(options.rules[0], [english]) is None
    assert dropped(options) == [ENGLISH.id]  # it still works


# The track order

SHOWN = [sig(ENGLISH), sig(COMMENTARY), sig(STEREO), sig(SUBTITLE), sig(OTHER_SUBTITLE)]


def test_moving_a_track_writes_the_order_of_every_signature() -> None:
    moved = move_track(TracksOptions(), SHOWN, SHOWN, 2, 0)
    assert moved.order == [s.match() for s in (SHOWN[2], SHOWN[0], SHOWN[1], SHOWN[3], SHOWN[4])]
    assert in_order(SHOWN, moved) == [2, 0, 1, 3, 4]


def test_a_track_moves_only_among_its_kind() -> None:
    # An audio track pushed past the subtitles stops at the last audio place; a subtitle stops at the first of its own.
    assert in_order(SHOWN, move_track(TracksOptions(), SHOWN, SHOWN, 0, 4)) == [1, 2, 0, 3, 4]
    assert in_order(SHOWN, move_track(TracksOptions(), SHOWN, SHOWN, 4, 0)) == [0, 1, 2, 4, 3]


def test_moving_a_track_back_to_where_the_files_have_it_stores_no_order() -> None:
    moved = move_track(TracksOptions(), SHOWN, SHOWN, 2, 0)
    shown = [SHOWN[n] for n in in_order(SHOWN, moved)]
    assert move_track(moved, shown, SHOWN, 0, 2).order == []


def test_a_moved_track_changes_the_plan_order_and_choices_still_apply() -> None:
    item = episode(VIDEO, ENGLISH, COMMENTARY, STEREO, SUBTITLE, OTHER_SUBTITLE)
    shown = [sig(t) for t in (ENGLISH, COMMENTARY, STEREO, SUBTITLE, OTHER_SUBTITLE)]
    options = choose(move_track(TracksOptions(), shown, shown, 4, 3), sig(COMMENTARY), TrackChoice(Verdict.DROP))
    result = plan(options, item)
    assert [k.track.id for k in result.kept] == [0, 1, 4, 7, 6]
    assert [d.track.id for d in result.dropped] == [2]
