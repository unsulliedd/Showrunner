from __future__ import annotations

from pathlib import Path

from showrunner.app.batches.batch import BatchKey, BatchKind, Media
from showrunner.app.batches.leave_out import LeftOut
from showrunner.app.jobs.groups import ChangeGroup

SEASON = BatchKey(BatchKind.SEASON, Media.EPISODES, "Show Name", 2020, 1)
MOVIE = BatchKey(BatchKind.MOVIE, Media.MOVIES, "Movie Title", 2021)


def test_groups_belong_to_their_batch_and_files_to_the_window() -> None:
    out = LeftOut()
    out.set_group(SEASON, ChangeGroup.NAMES, True)
    out.set_group(SEASON, ChangeGroup.TRACKS, True)
    assert out.groups_of(SEASON) == {ChangeGroup.NAMES, ChangeGroup.TRACKS}
    assert out.groups_of(MOVIE) == frozenset()
    out.set_group(SEASON, ChangeGroup.NAMES, False)
    out.set_group(SEASON, ChangeGroup.TRACKS, False)
    assert out.groups == {}  # a batch with every group in leaves no entry behind
    out.set_files([Path("a.mkv"), Path("b.mkv")], True)
    out.set_files([Path("a.mkv")], False)
    assert out.files == {Path("b.mkv")}
