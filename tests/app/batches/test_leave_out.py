from __future__ import annotations

from dataclasses import replace

from showrunner.app.batches.batch import BatchKey, BatchKind, Media
from showrunner.app.batches.leave_out import LeftOut
from showrunner.app.jobs.groups import ChangeGroup

SHOW = BatchKey(BatchKind.SHOW, Media.EPISODES, "Show Name", 2020)
SEASON = BatchKey(BatchKind.SEASON, Media.EPISODES, "Show Name", 2020, 1)
EPISODE = BatchKey(BatchKind.EPISODE, Media.EPISODES, "Show Name", 2020, 1, 3)
OTHER = BatchKey(BatchKind.EPISODE, Media.EPISODES, "Show Name", 2020, 1, 4)
MOVIE = BatchKey(BatchKind.MOVIE, Media.MOVIES, "Movie Title", 2021)


def test_a_group_left_out_reaches_the_places_inside_and_an_own_value_wins() -> None:
    out = LeftOut()
    out.set_group(SEASON, ChangeGroup.NAMES, True)
    out.set_group(SEASON, ChangeGroup.TRACKS, True)
    assert out.groups_of(SEASON) == out.groups_of(EPISODE) == {ChangeGroup.NAMES, ChangeGroup.TRACKS}
    assert out.groups_of(SHOW) == out.groups_of(MOVIE) == frozenset()
    # The episode puts Names back for itself only.
    out.set_group(EPISODE, ChangeGroup.NAMES, False)
    assert out.groups_of(EPISODE) == {ChangeGroup.TRACKS}
    assert out.groups_of(OTHER) == {ChangeGroup.NAMES, ChangeGroup.TRACKS}
    # The season puts it back too: the episode's value now equals what it receives, and goes.
    out.set_group(SEASON, ChangeGroup.NAMES, False)
    out.set_group(SEASON, ChangeGroup.TRACKS, False)
    assert out.empty


def test_not_this_time_is_a_value_of_the_file_s_place() -> None:
    out = LeftOut()
    out.set_file(EPISODE, True)
    assert out.file_out(EPISODE)
    assert not out.file_out(OTHER)
    out.set_file(EPISODE, False)
    assert out.empty


def test_clearing_a_place_ticks_everything_inside_it_again() -> None:
    out = LeftOut()
    out.set_group(SEASON, ChangeGroup.NAMES, True)
    out.set_group(EPISODE, ChangeGroup.TRACKS, True)
    out.set_file(EPISODE, True)
    out.set_file(MOVIE, True)
    out.clear(SEASON)
    assert out.groups_of(EPISODE) == frozenset()
    assert not out.file_out(EPISODE)
    assert out.file_out(MOVIE)  # another place, untouched


def test_clearing_a_place_puts_back_what_a_place_above_leaves_out() -> None:
    out = LeftOut()
    out.set_group(SHOW, ChangeGroup.NAMES, True)
    out.clear(SEASON)
    assert out.groups_of(SEASON) == out.groups_of(EPISODE) == frozenset()
    # The show and the seasons beside this one still leave it out.
    assert out.groups_of(SHOW) == {ChangeGroup.NAMES}
    assert out.groups_of(replace(SEASON, season=2)) == {ChangeGroup.NAMES}
    out.clear(SHOW)
    assert out.empty


def test_places_inside_that_hold_another_tick_are_counted_for_the_place_above() -> None:
    out = LeftOut()
    out.set_group(SEASON, ChangeGroup.TRACKS, True)
    assert out.held_inside(SHOW, ChangeGroup.TRACKS) == 1
    assert out.held_inside(SEASON, ChangeGroup.TRACKS) == 0  # its own value is what its box shows
    assert out.held_inside(SHOW, ChangeGroup.NAMES) == 0
    # An episode that puts it back differs from the season, not from the show.
    out.set_group(EPISODE, ChangeGroup.TRACKS, False)
    assert out.held_inside(SEASON, ChangeGroup.TRACKS) == 1
    assert out.held_inside(SHOW, ChangeGroup.TRACKS) == 1
