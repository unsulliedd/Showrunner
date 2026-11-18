from __future__ import annotations

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
