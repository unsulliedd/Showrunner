from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QApplication

from showrunner.app.library.library import Library, LibraryLoad, Mark
from showrunner.core.media import Episode, MediaItem
from showrunner.ui.i18n.catalog import tr
from showrunner.ui.library.model import Kind, LibraryModel


@pytest.fixture
def model(qapp: QApplication, sample_library: Library) -> LibraryModel:
    model = LibraryModel()
    model.set_library(sample_library)
    return model


def rows(model: LibraryModel, parent: QModelIndex | None = None) -> list[tuple[str, str, Mark]]:
    """Name, summary and mark of every row below `parent`, depth first."""
    parent = QModelIndex() if parent is None else parent
    found = []
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        found.append((index.data(), model.index(row, 1, parent).data(), model.mark(index)))
        found += rows(model, index)
    return found


def index_of(model: LibraryModel, library: Library, name: str) -> QModelIndex:
    return model.index_for_path(next(i.file.path for i in library.items if name in i.file.path.name))


def test_the_tree_groups_episodes_by_show_and_season_then_movies(model: LibraryModel) -> None:
    assert [(name, summary) for name, summary, _ in rows(model)] == [
        ("Alpha", "3"),
        ("Season 1", "2"),
        ("01  Pilot", "tur"),
        ("02  Second", "tur"),
        ("Season 2", "1"),
        ("01", "—"),
        ("Beta", "1"),
        ("Season 1", "1"),
        ("01", "—"),
        ("Movies", "1"),
        ("Movie Title (2016)", "—"),
    ]


def test_the_worst_mark_bubbles_up_to_every_parent(model: LibraryModel) -> None:
    assert [mark for _, _, mark in rows(model)] == [
        Mark.UNSURE,
        Mark.UNSURE,
        Mark.NONE,
        Mark.UNSURE,
        Mark.NONE,
        Mark.NONE,
        Mark.FAILED,
        Mark.FAILED,
        Mark.FAILED,
        Mark.NONE,
        Mark.NONE,
    ]


def test_a_row_knows_its_kind_and_the_videos_below_it(model: LibraryModel, sample_library: Library) -> None:
    alpha = model.index(0, 0)
    assert model.kind(alpha) is Kind.SHOW
    assert model.kind(model.index(0, 0, alpha)) is Kind.SEASON
    assert model.kind(index_of(model, sample_library, "Movie Title")) is Kind.MOVIE
    assert [p.name for p in model.video_paths(alpha)] == ["Alpha S01E01.mkv", "Alpha S01E02.mkv", "Alpha S02E01.mkv"]


def test_the_first_video_that_needs_a_look_is_found(model: LibraryModel, sample_library: Library) -> None:
    assert model.first_marked() == index_of(model, sample_library, "S01E02")
    model.set_library(Library())
    assert not model.first_marked().isValid()


def test_an_excluded_video_carries_no_dot_and_needs_no_look(model: LibraryModel, sample_library: Library) -> None:
    video = index_of(model, sample_library, "S01E02")
    path = model.path(video)
    looks = model.needs_look_count()
    assert model.dot(path) == "accent_ink"
    model.set_excluded([path])
    assert model.dot(path) is None
    assert model.needs_look_count() == looks - 1
    model.set_excluded([])
    assert model.dot(path) == "accent_ink"
    assert model.needs_look_count() == looks


def test_pairing_updates_the_rows_in_place(model: LibraryModel, sample_library: Library) -> None:
    video = index_of(model, sample_library, "S02E01")
    keep = QPersistentModelIndex(video)
    changes: list[None] = []
    model.library_changed.connect(lambda: changes.append(None))
    model.pair(sample_library.unpaired[0], model.path(video))
    assert keep.isValid()
    assert model.index(keep.row(), 1, keep.parent()).data() == "eng"
    assert model.library.unpaired == ()
    assert len(changes) == 1


def test_unpairing_clears_the_languages_of_the_row(model: LibraryModel, sample_library: Library) -> None:
    video = index_of(model, sample_library, "S01E01")
    path = model.path(video)
    model.unpair(sample_library.item(path).subtitles[0])
    assert model.index(video.row(), 1, video.parent()).data() == "—"
    assert len(model.library.unpaired) == 2


def test_choosing_an_alternative_clears_the_marks_of_the_row_and_its_parents(
    model: LibraryModel, sample_library: Library
) -> None:
    video = index_of(model, sample_library, "S01E02")
    path = model.path(video)
    model.pair_instead(path, sample_library.alternatives_of(path)[0])
    assert model.mark(video) is Mark.NONE
    assert model.mark(video.parent()) is Mark.NONE
    assert model.mark(video.parent().parent()) is Mark.NONE
    assert model.mark(model.index(1, 0)) is Mark.FAILED  # Beta is untouched


def test_adding_a_load_rebuilds_the_tree_with_the_new_videos(model: LibraryModel, sample_library: Library) -> None:
    extra = sample_library.items[-1]
    other = MediaItem(Episode("Gamma", 1, 1), replace(extra.file, path=Path("lib/Gamma/Gamma S01E01.mkv")), ())
    model.add(LibraryLoad(items=(other,)))
    assert [name for name, _, _ in rows(model) if name == "Gamma"] == ["Gamma"]
    assert model.library.counts().videos == 6


def test_a_path_is_looked_up_in_the_tree(model: LibraryModel) -> None:
    assert not model.index_for_path(Path("nowhere.mkv")).isValid()


def test_files_read_again_update_their_rows_or_rebuild_the_tree_for_a_new_name(
    model: LibraryModel, sample_library: Library
) -> None:
    first = sample_library.items[0]
    keep = QPersistentModelIndex(index_of(model, sample_library, "S01E01"))
    model.replace_files({first.file.path: replace(first.file, title="New")}, gone=[first.subtitles[0].path])
    assert keep.isValid()
    assert model.index(keep.row(), 1, keep.parent()).data() == tr("common.none")
    renamed = first.file.path.with_name("Alpha S01E01 new.mkv")
    model.replace_files({first.file.path: replace(first.file, path=renamed)})
    assert not keep.isValid()
    assert model.index_for_path(renamed).isValid()


def test_a_file_of_two_episodes_is_one_row_at_its_first_episode(model: LibraryModel, sample_library: Library) -> None:
    second = sample_library.items[1]
    ranged = replace(second, identity=replace(second.identity, episode=2, last_episode=3))
    other = replace(sample_library.items[0], identity=replace(sample_library.items[0].identity, episode=4))
    library = replace(sample_library, items=(other, ranged, *sample_library.items[2:]))
    model.set_library(library)
    names = [name for name, _, _ in rows(model) if name[:2].isdigit()]
    assert names[:2] == ["02  Second", "04  Pilot"]
    assert model.library.counts().videos == 5
